"""Ledger: immutable receipts and a hash-chained index on a protected branch.

Layout on the ledger branch (KAN-4 page 09, D-20):

    v1/ledger.jsonl                               one canonical entry per line
    v1/receipts/<decision_id>/<revision>.json     immutable canonical receipt

append() is a compare-and-swap: one commit whose only parent is the tip it
read, then a non-force ref update. A concurrent writer's update is not a fast
forward, so GitHub refuses it and the loser re-reads and retries. verify()
checks the chain and, given anchors (chain heads named by merge trailers,
unexpired checks or an owner copy), detects truncation or rewrite only while
such an anchor survives; it never treats an intact branch as proof of absence.

ponytail: ledger.jsonl is rewritten whole on every append and read through
the contents API (1 MB inline limit); shard by month when it nears that.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

GENESIS = "sha256:" + "0" * 64
LEDGER = "v1/ledger.jsonl"
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ENTRY_KEYS = (
    "seq",
    "prev_entry_digest",
    "decision_id",
    "receipt_revision",
    "receipt_digest",
    "subject_digest",
    "outcome",
    "created_at",
    "entry_digest",
)
RETRIES = 3


class LedgerError(Exception):
    """A refusal carrying its registered reason code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class ApiError(Exception):
    def __init__(self, status: int, detail: str = "") -> None:
        super().__init__(f"HTTP {status} {detail}")
        self.status = status


Api = Callable[[str, str, dict[str, Any] | None], Any]


def _lines(text: str) -> list[str]:
    """Index lines: append writes \n only, and values may hold other separators."""
    return [line for line in text.split("\n") if line]


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def receipt_path(decision_id: str, revision: str) -> str:
    if not (
        isinstance(decision_id, str)
        and isinstance(revision, str)
        and ID.fullmatch(decision_id)
        and ID.fullmatch(revision)
    ):
        raise LedgerError(
            "LEDGER_INVALID", f"unsafe receipt identifiers {decision_id!r}/{revision!r}"
        )
    return f"v1/receipts/{decision_id}/{revision}.json"


def entry(
    prev: dict[str, Any] | None,
    decision_id: str,
    revision: str,
    receipt: bytes,
    subject_digest: str,
    outcome: str,
    created_at: str,
) -> dict[str, Any]:
    body = {
        "seq": prev["seq"] + 1 if prev else 0,
        "prev_entry_digest": prev["entry_digest"] if prev else GENESIS,
        "decision_id": decision_id,
        "receipt_revision": revision,
        "receipt_digest": digest(receipt),
        "subject_digest": subject_digest,
        "outcome": outcome,
        "created_at": created_at,
    }
    return {**body, "entry_digest": digest(canonical(body))}


def verify(
    text: str, receipts: dict[str, bytes], anchors: tuple[str, ...] = ()
) -> list[str]:
    """Failures for a ledger index; empty means valid against these anchors."""
    failures: list[str] = []
    prev: dict[str, Any] | None = None
    heads: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for number, line in enumerate(_lines(text), 1):
        try:
            item = json.loads(line)
        except ValueError:
            failures.append(f"line {number}: not JSON")
            break
        if (
            not isinstance(item, dict)
            or tuple(sorted(item)) != tuple(sorted(ENTRY_KEYS))
            or canonical(item).decode() != line
        ):
            failures.append(f"line {number}: not a canonical entry")
            break
        expected_seq = prev["seq"] + 1 if prev else 0
        expected_prev = prev["entry_digest"] if prev else GENESIS
        if item["seq"] != expected_seq or item["prev_entry_digest"] != expected_prev:
            failures.append(
                f"line {number}: chain break (seq {item['seq']}, expected {expected_seq})"
            )
            break
        body = {k: v for k, v in item.items() if k != "entry_digest"}
        if digest(canonical(body)) != item["entry_digest"]:
            failures.append(f"line {number}: entry digest mismatch")
            break
        try:
            path = receipt_path(item["decision_id"], item["receipt_revision"])
        except LedgerError as exc:
            failures.append(f"line {number}: {exc}")
            break
        key = (item["decision_id"], item["receipt_revision"])
        if key in seen:
            failures.append(
                f"line {number}: duplicate receipt revision {key[0]}/{key[1]}"
            )
            break
        seen.add(key)
        if path not in receipts:
            failures.append(f"line {number}: receipt {path} missing")
        elif digest(receipts[path]) != item["receipt_digest"]:
            failures.append(f"line {number}: receipt {path} digest mismatch")
        heads.add(item["entry_digest"])
        prev = item
    for anchor in anchors:
        if anchor not in heads:
            failures.append(f"anchor {anchor} not in ledger: truncated or rewritten")
    return failures


@dataclass(frozen=True)
class State:
    tip: str
    tree: str
    text: str


def _file(api: Api, repo: str, path: str, ref: str) -> bytes | None:
    try:
        data = api("GET", f"repos/{repo}/contents/{path}?ref={ref}", None)
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        # Over 1 MB the contents API returns no inline content; never read that as empty.
        raise ApiError(
            0, f"{path} has no inline base64 content (over the 1 MB contents limit?)"
        )
    return base64.b64decode(data["content"])


def read(api: Api, repo: str, ref: str) -> State:
    tip = api("GET", f"repos/{repo}/git/ref/heads/{ref}", None)["object"]["sha"]
    tree = api("GET", f"repos/{repo}/git/commits/{tip}", None)["tree"]["sha"]
    try:
        text = (_file(api, repo, LEDGER, tip) or b"").decode()
    except UnicodeDecodeError as exc:
        raise LedgerError("LEDGER_INVALID", f"{LEDGER} is not UTF-8: {exc}") from None
    return State(tip, tree, text)


def _receipts(api: Api, repo: str, state: State) -> dict[str, bytes]:
    """Receipts the index names; malformed lines are left for verify() to reject."""
    found: dict[str, bytes] = {}
    for line in _lines(state.text):
        try:
            item = json.loads(line)
            path = receipt_path(item["decision_id"], item["receipt_revision"])
        except (ValueError, KeyError, TypeError, LedgerError):
            continue
        data = _file(api, repo, path, state.tip)
        if data is not None:
            found[path] = data
    return found


def candidate(
    api: Api, repo: str, state: State, files: dict[str, bytes], message: str
) -> str:
    """One commit whose only parent is ``state.tip``; nothing is published yet."""
    tree = api(
        "POST",
        f"repos/{repo}/git/trees",
        {
            "base_tree": state.tree,
            "tree": [
                {"path": p, "mode": "100644", "type": "blob", "content": b.decode()}
                for p, b in files.items()
            ],
        },
    )["sha"]
    return api(
        "POST",
        f"repos/{repo}/git/commits",
        {"message": message, "tree": tree, "parents": [state.tip]},
    )["sha"]


def advance(api: Api, repo: str, ref: str, sha: str) -> None:
    api("PATCH", f"repos/{repo}/git/refs/heads/{ref}", {"sha": sha, "force": False})


def append(
    api: Api,
    repo: str,
    ref: str,
    decision_id: str,
    revision: str,
    receipt: bytes,
    subject_digest: str,
    outcome: str,
    created_at: str,
) -> dict[str, Any] | None:
    """Append one receipt; None when identical bytes are already recorded."""
    path = receipt_path(decision_id, revision)
    for _attempt in range(RETRIES):
        try:
            state = read(api, repo, ref)
            failures = verify(state.text, _receipts(api, repo, state))
            if failures:
                raise LedgerError("LEDGER_INVALID", "; ".join(failures))
            lines = _lines(state.text)
            existing = _file(api, repo, path, state.tip)
            if existing is not None:
                if existing != receipt:
                    raise LedgerError(
                        "RECEIPT_COLLISION", f"{path} already holds different bytes"
                    )
                recorded = [
                    item
                    for item in map(json.loads, lines)
                    if (item["decision_id"], item["receipt_revision"])
                    == (decision_id, revision)
                ]
                if not recorded:
                    raise LedgerError(
                        "LEDGER_INVALID",
                        f"{path} exists but the index does not record it",
                    )
                if (recorded[0]["subject_digest"], recorded[0]["outcome"]) != (
                    subject_digest,
                    outcome,
                ):
                    # created_at is when it was first recorded, so a later retry may differ.
                    raise LedgerError(
                        "RECEIPT_COLLISION",
                        f"{path} is recorded with another subject or outcome",
                    )
                return None
            prev = json.loads(lines[-1]) if lines else None
            item = entry(
                prev,
                decision_id,
                revision,
                receipt,
                subject_digest,
                outcome,
                created_at,
            )
            text = state.text + canonical(item).decode() + "\n"
            sha = candidate(
                api,
                repo,
                state,
                {path: receipt, LEDGER: text.encode()},
                f"ledger: {decision_id} {revision}",
            )
            try:
                advance(api, repo, ref, sha)
            except ApiError as exc:
                if exc.status in (409, 422):
                    continue  # lost the race: re-read and rebuild
                raise
            if (
                _file(api, repo, LEDGER, sha) != text.encode()
                or _file(api, repo, path, sha) != receipt
            ):
                raise LedgerError(
                    "LEDGER_INVALID", "read-back differs from what was written"
                )
            return item
        except ApiError as exc:
            raise LedgerError("LEDGER_UNAVAILABLE", str(exc)) from None
    raise LedgerError("LEDGER_UNAVAILABLE", f"lost the ref race {RETRIES} times")


def gh_api(method: str, path: str, payload: dict[str, Any] | None) -> Any:
    """The provider through ``gh api``; GH_TOKEN selects the identity."""
    args = [
        "gh",
        "api",
        "-X",
        method,
        path,
        "-H",
        "Accept: application/vnd.github+json",
    ]
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(
        args,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
    )  # noqa: S603
    if result.returncode:
        status = re.search(r"HTTP (\d{3})", result.stderr)
        raise ApiError(
            int(status.group(1)) if status else 0, result.stderr.strip()[:300]
        )
    return json.loads(result.stdout) if result.stdout.strip() else None


def drill(api: Api, repo: str, ref: str, stamp: str) -> list[tuple[str, bool, str]]:
    """KAN-30 Stage B writer drill, run as App M. Returns (step, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    def record(step: str, passed: bool, detail: str) -> None:
        results.append((step, passed, detail))

    receipt = canonical({"drill": stamp, "outcome": "AUTHORIZE"})
    first = append(
        api,
        repo,
        ref,
        f"drill-{stamp}",
        "r1",
        receipt,
        digest(b"subject"),
        "AUTHORIZE",
        stamp,
    )
    record("L1 App M appends a receipt", first is not None, json.dumps(first))
    record(
        "L2 identical retry appends nothing",
        append(
            api,
            repo,
            ref,
            f"drill-{stamp}",
            "r1",
            receipt,
            digest(b"subject"),
            "AUTHORIZE",
            stamp,
        )
        is None,
        "",
    )
    try:
        append(
            api,
            repo,
            ref,
            f"drill-{stamp}",
            "r1",
            canonical({"other": 1}),
            digest(b"subject"),
            "AUTHORIZE",
            stamp,
        )
        record("L3 different bytes at the same revision collide", False, "accepted")
    except LedgerError as exc:
        record(
            "L3 different bytes at the same revision collide",
            exc.code == "RECEIPT_COLLISION",
            str(exc),
        )
    state = read(api, repo, ref)
    a = candidate(api, repo, state, {f"v1/drill/{stamp}-a": b"a"}, "drill race a")
    b = candidate(api, repo, state, {f"v1/drill/{stamp}-b": b"b"}, "drill race b")
    advance(api, repo, ref, a)
    try:
        advance(api, repo, ref, b)
        record(
            "L4 second writer from the same parent loses",
            False,
            "non-fast-forward accepted",
        )
    except ApiError as exc:
        record(
            "L4 second writer from the same parent loses",
            exc.status in (409, 422),
            str(exc),
        )
    # The race files are not ledger entries; a real loser re-reads and appends (L5).
    second = append(
        api,
        repo,
        ref,
        f"drill-{stamp}",
        "r2",
        canonical({"drill": stamp, "rev": 2}),
        digest(b"subject"),
        "AUTHORIZE",
        stamp,
    )
    record(
        "L5 loser re-reads and appends without loss",
        second is not None and second["seq"] == first["seq"] + 1,
        json.dumps(second),
    )
    try:
        api(
            "PATCH",
            f"repos/{repo}/git/refs/heads/{ref}",
            {"sha": state.tip, "force": True},
        )
        record("L6 App M cannot force-push the ledger", False, "force update accepted")
    except ApiError as exc:
        record(
            "L6 App M cannot force-push the ledger",
            exc.status in (403, 409, 422),
            str(exc),
        )
    try:
        api("DELETE", f"repos/{repo}/git/refs/heads/{ref}", None)
        record("L7 App M cannot delete the ledger", False, "delete accepted")
    except ApiError as exc:
        record(
            "L7 App M cannot delete the ledger", exc.status in (403, 409, 422), str(exc)
        )
    final = read(api, repo, ref)
    failures = verify(
        final.text,
        _receipts(api, repo, final),
        (second["entry_digest"],) if second else (),
    )
    record(
        "L8 read-back chain verifies against its anchor",
        not failures,
        "; ".join(failures) or final.tip,
    )
    return results


INTEGRITY_RULES = {"deletion", "non_fast_forward", "required_linear_history"}


def _glob(pattern: str) -> re.Pattern[str]:
    """GitHub's ruleset fnmatch with FNM_PATHNAME: `*` and `?` stop at `/`, `**` crosses it.

    ponytail: bracket classes are matched literally; GitHub ref patterns here never use them.
    """
    out = ""
    for token in re.split(r"(\*\*|\*|\?)", pattern):
        out += {"**": ".*", "*": "[^/]*", "?": "[^/]"}.get(token, re.escape(token))
    return re.compile(out + r"\Z")


def _targets(ruleset: dict[str, Any], ref: str) -> bool:
    names = (ruleset.get("conditions") or {}).get("ref_name") or {}
    full = f"refs/heads/{ref}"

    def hit(pattern: str) -> bool:
        return pattern == "~ALL" or bool(_glob(pattern).match(full))

    return any(hit(p) for p in names.get("include", [])) and not any(
        hit(p) for p in names.get("exclude", [])
    )


def ruleset_failures(
    rulesets: list[dict[str, Any]], ref: str, app_id: int
) -> list[str]:
    """D-20 topology check on the active rulesets targeting ``ref``; empty means sound.

    One writer ruleset restricts updates and creation, with App M as its only
    (always) bypass; a separate integrity ruleset restricts deletion, force
    push and non-linear history with no bypass at all.
    """
    active = [
        r for r in rulesets if r.get("enforcement") == "active" and _targets(r, ref)
    ]
    app = [{"actor_type": "Integration", "actor_id": app_id, "bypass_mode": "always"}]
    failures = []

    def types(r: dict[str, Any]) -> set[str]:
        return {rule["type"] for rule in r.get("rules", [])}

    writers = [r for r in active if "update" in types(r)]
    integrity = [r for r in active if INTEGRITY_RULES <= types(r)]
    if len(writers) != 1 or not {"update", "creation"} <= types(writers[0]):
        failures.append(
            f"want exactly one writer ruleset with update+creation, found {len(writers)}"
        )
    elif [
        {k: a.get(k) for k in ("actor_type", "actor_id", "bypass_mode")}
        for a in writers[0].get("bypass_actors", [])
    ] != app:
        failures.append(f"writer ruleset bypass must be exactly App {app_id} (always)")
    if not any(not r.get("bypass_actors") for r in integrity):
        failures.append(
            "no integrity ruleset (deletion, non_fast_forward, linear history) without bypass actors"
        )
    for r in active:
        if writers and r is not writers[0] and r.get("bypass_actors"):
            failures.append(
                f"ruleset {r.get('name')!r} has bypass actors; only the writer ruleset may"
            )
        if types(r) & INTEGRITY_RULES and "update" in types(r):
            failures.append(
                f"ruleset {r.get('name')!r} mixes writer and integrity rules, so its bypass escapes both"
            )
        if any(a.get("bypass_mode") == "exempt" for a in r.get("bypass_actors", [])):
            failures.append(
                f"ruleset {r.get('name')!r} has an exempt bypass (banned, D-5)"
            )
    return failures


DRILL_REF = "refs/heads/mandate-g0/ledger"
DRILL_NAMES = ("mandate-ledger-writer-drill", "mandate-ledger-integrity-drill")


def drill_ruleset_ids(rulesets: list[dict[str, Any]]) -> list[int]:
    """IDs of exactly the two temporary drill rulesets, or a refusal.

    Each name must appear once and target only the drill ref, so teardown can
    never select another ruleset, such as a later production ledger one.
    """
    ids = []
    for name in DRILL_NAMES:
        matches = [r for r in rulesets if r.get("name") == name]
        if len(matches) != 1:
            raise LedgerError(
                "LEDGER_INVALID",
                f"expected one ruleset named {name}, found {len(matches)}",
            )
        names = (matches[0].get("conditions") or {}).get("ref_name") or {}
        if names.get("include") != [DRILL_REF] or names.get("exclude"):
            raise LedgerError(
                "LEDGER_INVALID", f"{name} targets {names}, not only {DRILL_REF}"
            )
        ids.append(matches[0]["id"])
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KAN-30 ledger drill and topology check"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser(
        "drill", help="writer drill as App M (writes only to the given ref)"
    )
    run.add_argument("repository")
    run.add_argument("ref")
    run.add_argument("stamp", help="unique run stamp, e.g. the workflow run ID")
    check = sub.add_parser("rulesets", help="read-only D-20 ruleset topology check")
    check.add_argument("repository")
    check.add_argument("ref")
    check.add_argument("app_id", type=int)
    teardown = sub.add_parser(
        "drill-rulesets", help="print the two drill ruleset IDs, or refuse"
    )
    teardown.add_argument("repository")
    args = parser.parse_args(argv)
    if args.command == "drill-rulesets":
        summaries = gh_api(
            "GET", f"repos/{args.repository}/rulesets?per_page=100", None
        )
        details = [
            gh_api("GET", f"repos/{args.repository}/rulesets/{r['id']}", None)
            for r in summaries
        ]
        try:
            ids = drill_ruleset_ids(details)
        except LedgerError as exc:
            print(f"refusing teardown: {exc}", file=sys.stderr)
            return 1
        for ruleset in details:
            if ruleset["id"] in ids:
                print(f"{ruleset['id']} {ruleset['name']}", file=sys.stderr)
        print(" ".join(map(str, ids)))
        return 0
    if args.command == "rulesets":
        summaries = gh_api(
            "GET",
            f"repos/{args.repository}/rulesets?includes_parents=true&per_page=100",
            None,
        )
        rulesets = [
            gh_api("GET", f"repos/{args.repository}/rulesets/{r['id']}", None)
            for r in summaries
        ]
        failures = ruleset_failures(rulesets, args.ref, args.app_id)
        print(
            "\n".join(f"FAIL  {f}" for f in failures)
            or f"PASS  D-20 topology on {args.ref}"
        )
        return 1 if failures else 0
    results = drill(gh_api, args.repository, args.ref, args.stamp)
    for step, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {step}  {detail}")
    return 0 if all(p for _, p, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
