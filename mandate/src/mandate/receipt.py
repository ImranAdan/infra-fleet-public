"""Receipts: one versioned record per decision revision, kept in the ledger.

A ``decision_id`` names the immutable subject: repository, pull request,
head, base, delegation revision and enforcement snapshot. Any drift is a new
ID. Under one ID, receipts are revisions r1, r2, ...: record() appends the
next one only when the decision's meaning (everything but the clock and the
revision) differs from the latest, so rerunning identical inputs is a no-op,
and flipping back to an earlier result is a new revision, never a reuse.

reconcile_check() is the only check publisher: it shows the ledger's latest
revision, and every writer runs as one serialized job per pull request.

The merge commit is the anchor: trailers() records a fresh AUTHORIZE decision
for the subject the worker acted on and names that latest revision's receipt
digest and chain head. audit() checks a ledger against those anchors offline and says
literally what it cannot see. The anchor is repository-local, not an
independent transparency log: an owner or bypass actor who rewrites history,
or a key holder who appends after the last anchor, is a residual risk that
audit() reports as "not detectable with available anchor".
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from mandate import ledger as l
from mandate.decision import Decision

SCHEMA_VERSION = 1
CHECK_NAME = "mandate/decision"
SHADOW = "shadow"  # the enforcement snapshot of a decision that grants nothing
LIVE = re.compile(r"^sha256:[0-9a-f]{64}$")  # a real enforcement snapshot digest
# One writer per pull request: writers are workflows called with a ``pr`` input,
# so every caller computes this same group.
CANONICAL_GROUP = "mandate-decision-${{ github.repository }}-${{ inputs.pr }}"
_WRITES = re.compile(
    r"(?m)mandate(\.| import )receipt|src/mandate/receipt\.py"
    r"|^\s*(permission-)?checks:\s*write\b|^\s*permissions:\s*write-all\b"
)
TRAILERS = ("Mandate-Decision", "Mandate-Receipt-Digest", "Mandate-Chain-Head")
_TRAILER = re.compile(rf"(?m)^({'|'.join(TRAILERS)}): (\S+)$")
_CLOCK = ("evaluated_at", "receipt_revision")
SUMMARY_LIMIT = 65535  # GitHub's check-run output.summary maximum


def _subject(
    repository: str, pull_request: int, head: str, base: str, policy: str, enforcement: str
) -> dict[str, Any]:
    return {
        "repository": repository,
        "pull_request": pull_request,
        "head_sha": head,
        "base_sha": base,
        "policy": policy,
        "enforcement": enforcement,
    }


def decision_id(
    repository: str, pull_request: int, head: str, base: str, policy: str, enforcement: str
) -> str:
    subject = _subject(repository, pull_request, head, base, policy, enforcement)
    return "d-" + l.digest(l.canonical(subject)).removeprefix("sha256:")


def build(
    decision: Decision,
    pull_request: int,
    enforcement: str,
    *,
    versions: dict[str, Any],
    actors: dict[str, Any],
    evaluated_at: str,
) -> dict[str, Any]:
    """The receipt body for one decision; record() adds its revision."""
    s = decision.subject
    subject = _subject(s.repository, pull_request, s.head_sha, s.base_sha, s.policy, enforcement)
    subject_digest = l.digest(l.canonical(subject))
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_id": "d-" + subject_digest.removeprefix("sha256:"),
        "subject": subject,
        "subject_digest": subject_digest,
        "decision": decision.to_dict(),
        "versions": versions,
        "actors": actors,
        "evaluated_at": evaluated_at,
    }


def semantic(receipt: dict[str, Any]) -> dict[str, Any]:
    """What the receipt says, without when it was said or its revision number."""
    return {k: v for k, v in receipt.items() if k not in _CLOCK}


def _latest(
    api: l.Api, repo: str, ref: str, did: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, bytes]]:
    """(all entries, this decision's entries, receipts) from a verified ledger."""
    try:
        state = l.read(api, repo, ref)
        stored = l._receipts(api, repo, state)
    except l.ApiError as exc:
        raise l.LedgerError("LEDGER_UNAVAILABLE", str(exc)) from None
    failures = l.verify(state.text, stored)
    if failures:
        raise l.LedgerError("LEDGER_INVALID", "; ".join(failures))
    entries = [json.loads(x) for x in l._lines(state.text)]
    return entries, [x for x in entries if x["decision_id"] == did], stored


def record(
    api: l.Api, repo: str, ref: str, receipt: dict[str, Any]
) -> tuple[dict[str, Any], str, bool]:
    """(ledger entry for this decision's latest revision, chain head, appended)."""
    did = receipt["decision_id"]
    for _attempt in range(l.RETRIES):
        entries, mine, stored = _latest(api, repo, ref, did)
        if mine:
            latest = json.loads(stored[l.receipt_path(did, mine[-1]["receipt_revision"])])
            if semantic(latest) == semantic(receipt):
                return mine[-1], entries[-1]["entry_digest"], False
        revision = f"r{len(mine) + 1}"
        try:
            item = l.append(
                api,
                repo,
                ref,
                did,
                revision,
                l.canonical({**receipt, "receipt_revision": revision}),
                receipt["subject_digest"],
                receipt["decision"]["outcome"],
                receipt["evaluated_at"],
            )
        except l.LedgerError as exc:
            if exc.code == "RECEIPT_COLLISION":
                continue  # a concurrent writer took this revision: re-read
            raise
        if item is not None:
            return item, item["entry_digest"], True
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"lost the revision race {l.RETRIES} times")


def _show(
    api: l.Api, repo: str, receipt: dict[str, Any], entry: dict[str, Any], chain_head: str, app_id: int
) -> None:
    """Make every ``mandate/decision`` run of ours for this decision show this revision."""
    head, did = receipt["subject"]["head_sha"], receipt["decision_id"]
    outcome, revision = receipt["decision"]["outcome"], entry["receipt_revision"]
    # From the recorded snapshot, never a caller flag: only a live sha256
    # snapshot can pass, shadow is neutral, anything else fails closed.
    enforcement = receipt["subject"]["enforcement"]
    shadow = enforcement == SHADOW
    passes = outcome == "AUTHORIZE" and bool(LIVE.match(enforcement))
    conclusion = "neutral" if shadow else ("success" if passes else "failure")
    reasons = "".join(
        f"\n- `{x['code']}` ({x['outcome']}, {x['owner']}): {x['detail'][:200]}"
        for x in receipt["decision"]["reasons"]
    )
    summary = (
        f"Receipt `{did}/{revision}`, digest `{entry['receipt_digest']}`, "
        f"chain head `{chain_head}`."
        + (" Shadow mode: this decision grants nothing." if shadow else "")
        + reasons
    )
    encoded = summary.encode("utf-8")
    if len(encoded) > SUMMARY_LIMIT:  # bytes, cut on a character boundary
        cut = "\n- … more reasons in the receipt"
        keep = encoded[: SUMMARY_LIMIT - len(cut.encode("utf-8"))]
        summary = keep.decode("utf-8", "ignore") + cut
    payload = {
        "name": CHECK_NAME,
        "external_id": did,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": f"{outcome} ({revision})", "summary": summary},
    }
    runs: list[dict[str, Any]] = []
    for page in range(1, 1000):  # filter=all: the default lists only the newest run
        data = api(
            "GET",
            f"repos/{repo}/commits/{head}/check-runs?check_name={quote(CHECK_NAME)}"
            f"&filter=all&per_page=100&page={page}",
            None,
        )
        runs += data["check_runs"]
        if not data["check_runs"] or len(runs) >= data["total_count"]:
            break
    mine = [
        x for x in runs if x.get("external_id") == did and (x.get("app") or {}).get("id") == app_id
    ]
    if not mine:
        api("POST", f"repos/{repo}/check-runs", {**payload, "head_sha": head})
    for run in mine:  # a past race can leave two; each must show the latest
        shown = run.get("output") or {}
        if run.get("conclusion") != conclusion or any(
            shown.get(k) != v for k, v in payload["output"].items()
        ):  # GitHub adds text and annotation fields we never send
            api("PATCH", f"repos/{repo}/check-runs/{run['id']}", payload)


def reconcile_check(api: l.Api, repo: str, ref: str, did: str, *, app_id: int) -> dict[str, Any]:
    """Show the ledger's latest revision of ``did`` on its ``mandate/decision`` check.

    The only check publisher. The caller names a decision, never a revision,
    so a delayed caller cannot choose a superseded one. The Checks API has no
    compare-and-swap, so two boundaries hold the check to the ledger:

    - one writer per pull request: every job that records receipts or writes
      checks runs in CANONICAL_GROUP without cancelling in progress
      (serial_violations() enforces it over the workflows);
    - if the ledger moved while this ran (only possible when that boundary is
      bypassed), it shows the newer revision before returning.

    Only runs created by ``app_id`` (the publisher App) are ours. The
    conclusion follows the receipt's recorded enforcement: a shadow receipt is
    always neutral. Returns the ledger entry it left on display.
    """
    for _attempt in range(l.RETRIES):
        entries, mine, stored = _latest(api, repo, ref, did)
        if not mine:
            raise l.LedgerError("CONTRACT_ERROR", f"no receipt recorded for {did}")
        entry = mine[-1]
        receipt = json.loads(stored[l.receipt_path(did, entry["receipt_revision"])])
        _show(api, repo, receipt, entry, entries[-1]["entry_digest"], app_id)
        if _latest(api, repo, ref, did)[1][-1] == entry:
            return entry
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"the ledger kept moving under {did}")


def _serialized(block: str) -> bool:
    """Whether a workflow header or job block declares the canonical group."""
    found = re.search(r"(?m)^( *)concurrency:[ \t]*\n((?:\1 +\S.*\n?)+)", block)
    if not found:
        return False
    keys = dict(re.findall(r"(?m)^ +([\w-]+):[ \t]*(.*?)[ \t]*$", found.group(2)))
    return (
        keys.get("group", "").strip("'\"") == CANONICAL_GROUP
        and keys.get("cancel-in-progress") == "false"
    )


def _unscoped_token(block: str) -> bool:
    """An App token step without permission inputs carries every App
    permission (the Mandate App has checks: write), so it counts as a writer."""
    return any(
        "create-github-app-token" in step and not re.search(r"(?m)^\s*permission-[\w-]+:", step)
        for step in re.split(r"(?m)^(?= *- )", block)
    )


def serial_violations(workflows: dict[str, str]) -> list[str]:
    """``file:job`` for each job that records receipts or can write checks
    outside the canonical per-PR concurrency group."""
    bad = []
    for name, text in sorted(workflows.items()):
        header, _, body = text.partition("\njobs:\n")
        jobs = re.findall(r"(?m)^  ([\w-]+):[ \t]*\n((?:(?:    .*)?\n?)*)", body)
        if not jobs and _WRITES.search(text):
            bad.append(f"{name}:?")  # writes, but no job this parser can read: fail closed
        for job, block in jobs:
            writes = _WRITES.search(header) or _WRITES.search(block) or _unscoped_token(block)
            if writes and not (_serialized(header) or _serialized(block)):
                bad.append(f"{name}:{job}")
    return bad


def trailers(
    api: l.Api, repo: str, ref: str, subject: dict[str, Any], fresh: dict[str, Any]
) -> str:
    """Merge-commit trailers after final revalidation.

    ``subject`` is what the merge worker acted on; ``fresh`` is a receipt from
    a decision taken just now. It must still be about that subject and
    AUTHORIZE. It is then recorded (a no-op when it is already the latest
    revision), so the trailers always name this decision's latest revision,
    never a superseded one a stale worker still holds.
    """
    for field, code in (
        ("head_sha", "HEAD_CHANGED"),
        ("base_sha", "BASE_CHANGED"),
        ("enforcement", "ENFORCEMENT_DRIFT"),
    ):
        if fresh["subject"][field] != subject[field]:
            raise l.LedgerError(code, f"{field} {subject[field]} is now {fresh['subject'][field]}")
    if fresh["subject"] != subject:
        raise l.LedgerError("CONTRACT_ERROR", "the fresh decision is about another subject")
    if not LIVE.match(subject["enforcement"]):
        raise l.LedgerError(
            "CONTRACT_ERROR", f"enforcement {subject['enforcement']!r} is not a live snapshot: shadow grants nothing"
        )
    if fresh["decision"]["outcome"] != "AUTHORIZE":
        raise l.LedgerError("CONTRACT_ERROR", f"fresh outcome is {fresh['decision']['outcome']}")
    entry, chain_head, _ = record(api, repo, ref, fresh)
    values = (entry["decision_id"], entry["receipt_digest"], chain_head)
    return "\n".join(f"{k}: {v}" for k, v in zip(TRAILERS, values))


def parse_trailers(message: str) -> dict[str, str] | None:
    """The three trailers from the final paragraph, or None when any is missing or repeated."""
    paragraphs = [p for p in message.replace("\r\n", "\n").strip().split("\n\n") if p.strip()]
    found = _TRAILER.findall(paragraphs[-1]) if paragraphs else []
    names = [k for k, _ in found]
    if sorted(names) != sorted(TRAILERS):
        return None
    return dict(found)


def audit(
    text: str, receipts: dict[str, bytes], anchors: list[dict[str, str]]
) -> tuple[list[str], list[str]]:
    """(failures, limits) for a ledger against merge-commit anchors.

    Failures are detected tampering. Limits state what the anchors cannot
    show, so an intact-looking branch is never reported as proof.
    """
    failures = l.verify(text, receipts, tuple(a["Mandate-Chain-Head"] for a in anchors))
    if failures:
        return failures, []
    entries = [json.loads(x) for x in l._lines(text)]
    position = {x["entry_digest"]: i for i, x in enumerate(entries)}
    last = -1
    for anchor in anchors:
        at = position[anchor["Mandate-Chain-Head"]]
        last = max(last, at)
        if not any(
            (x["decision_id"], x["receipt_digest"])
            == (anchor["Mandate-Decision"], anchor["Mandate-Receipt-Digest"])
            for x in entries[: at + 1]
        ):
            failures.append(
                f"anchor {anchor['Mandate-Chain-Head']}: receipt {anchor['Mandate-Receipt-Digest']} "
                f"for {anchor['Mandate-Decision']} not recorded at or before it"
            )
    tail = len(entries) - 1 - last
    limits = []
    if last < 0:
        limits.append(
            f"no anchor: truncation, rewrite or forged appends (key compromise) in all "
            f"{len(entries)} entries are not detectable with available anchor"
        )
    else:  # even at zero: a tail truncated back to the anchor looks the same
        limits.append(
            f"{tail} {'entry' if tail == 1 else 'entries'} visible after the last anchor: truncation, "
            "rewrite or forged appends (key compromise) after it are not detectable with available anchor"
        )
    return failures, limits
