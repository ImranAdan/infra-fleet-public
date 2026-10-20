"""Ledger checks (KAN-30 Stage A). Run: python3 mandate/tests/test_ledger.py

Golden vectors, the anchor attack matrix and a two-writer compare-and-swap
race, against an in-memory Git that enforces fast-forward-only ref updates
and the D-20 rulesets the way GitHub does. The provider drill (Stage B) runs
the same append() and drill() against the real API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import ledger as l  # noqa: E402

REPO, REF = "o/r", "mandate-ledger"


class FakeGit:
    """Refs, commits and trees; ref updates must fast-forward unless forced,
    and the integrity ruleset refuses force and delete for everyone."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        root = self._put({"files": {"README.md": b"ledger"}})
        self.refs = {REF: self._put({"tree": root, "parents": []})}
        self.before_advance = None  # a concurrent writer, run once

    def _put(self, obj: dict) -> str:
        sha = hashlib.sha1(repr(sorted(obj.items())).encode()).hexdigest()
        self.objects[sha] = obj
        return sha

    def _ancestors(self, sha: str) -> set[str]:
        seen, stack = set(), [sha]
        while stack:
            s = stack.pop()
            if s not in seen:
                seen.add(s)
                stack += self.objects[s]["parents"]
        return seen

    def files(self, ref: str) -> dict[str, bytes]:
        return self.objects[self.objects[self.refs[ref]]["tree"]]["files"]

    def __call__(self, method: str, path: str, payload):
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if method == "GET" and tail.startswith("git/ref/heads/"):
            return {"object": {"sha": self.refs[tail.removeprefix("git/ref/heads/")]}}
        if method == "GET" and tail.startswith("git/commits/"):
            return {
                "tree": {"sha": self.objects[tail.removeprefix("git/commits/")]["tree"]}
            }
        if method == "GET" and tail.startswith("contents/"):
            name, ref = tail.removeprefix("contents/").split("?ref=")
            files = self.objects[self.objects[ref]["tree"]]["files"]
            if name not in files:
                raise l.ApiError(404)
            return {"content": base64.b64encode(files[name]).decode(), "encoding": "base64"}
        if method == "POST" and tail == "git/trees":
            files = dict(self.objects[payload["base_tree"]]["files"])
            files.update({t["path"]: t["content"].encode() for t in payload["tree"]})
            return {"sha": self._put({"files": files})}
        if method == "POST" and tail == "git/commits":
            return {
                "sha": self._put(
                    {"tree": payload["tree"], "parents": payload["parents"]}
                )
            }
        if method == "PATCH" and tail.startswith("git/refs/heads/"):
            if self.before_advance:
                racer, self.before_advance = self.before_advance, None
                racer()
            name = tail.removeprefix("git/refs/heads/")
            if payload["force"] or self.refs[name] not in self._ancestors(
                payload["sha"]
            ):
                raise l.ApiError(422, "non-fast-forward or forced update refused")
            self.refs[name] = payload["sha"]
            return {}
        if method == "DELETE":
            raise l.ApiError(422, "deletion refused by ruleset")
        raise AssertionError(f"unexpected {method} {path}")


def receipts(git: FakeGit) -> dict[str, bytes]:
    return {p: b for p, b in git.files(REF).items() if p.startswith("v1/receipts/")}


def main() -> int:
    # Golden vector: one fixed entry has one fixed digest (canonical JSON, SHA-256).
    receipt = l.canonical({"decision_id": "d1", "outcome": "AUTHORIZE"})
    first = l.entry(
        None,
        "d1",
        "r1",
        receipt,
        "sha256:" + "1" * 64,
        "AUTHORIZE",
        "2026-10-20T00:00:00Z",
    )
    assert first["seq"] == 0 and first["prev_entry_digest"] == l.GENESIS
    assert first["receipt_digest"] == "sha256:" + hashlib.sha256(receipt).hexdigest()
    assert (
        first["entry_digest"]
        == "sha256:adbabec8c1cf98abb337dad6f4213d6da5692c06d929f37c3a341294d40fbad2"
    )
    golden = l.digest(
        l.canonical({k: v for k, v in first.items() if k != "entry_digest"})
    )
    assert first["entry_digest"] == golden

    # Append, idempotent retry, collision.
    git = FakeGit()
    e1 = l.append(git, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    assert e1 is not None and e1["seq"] == 0
    tip = git.refs[REF]
    assert (
        l.append(git, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
        is None
    )
    assert git.refs[REF] == tip, "an identical retry must append nothing"
    try:
        l.append(git, REPO, REF, "d1", "r1", b"{}", "sha256:s", "AUTHORIZE", "t1")
    except l.LedgerError as exc:
        assert exc.code == "RECEIPT_COLLISION", exc
    else:
        raise AssertionError("different bytes at one revision were accepted")

    # Two-writer race: a concurrent append lands between our read and our ref
    # update; our non-force update is refused, we re-read, and nothing is lost.
    git.before_advance = lambda: l.append(
        git, REPO, REF, "d2", "r1", b'{"w":2}', "sha256:s", "VERIFY", "t2"
    )
    e3 = l.append(git, REPO, REF, "d3", "r1", b'{"w":3}', "sha256:s", "BLOCK", "t3")
    text = git.files(REF)[l.LEDGER].decode()
    assert [json.loads(x)["decision_id"] for x in text.splitlines()] == [
        "d1",
        "d2",
        "d3",
    ], text
    assert e3["seq"] == 2 and l.verify(text, receipts(git), (e3["entry_digest"],)) == []

    # A writer that loses every race gives up with LEDGER_UNAVAILABLE.
    class AlwaysLose(FakeGit):
        def __call__(self, method, path, payload):
            if method == "PATCH":
                raise l.ApiError(422)
            return super().__call__(method, path, payload)

    try:
        l.append(AlwaysLose(), REPO, REF, "d9", "r1", b"{}", "sha256:s", "VERIFY", "t")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_UNAVAILABLE", exc
    else:
        raise AssertionError("an exhausted race was reported as success")

    # A corrupted ledger refuses further appends.
    bad = FakeGit()
    l.append(bad, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    bad.objects[bad.objects[bad.refs[REF]]["tree"]]["files"][l.LEDGER] = b'{"seq":5}\n'
    try:
        l.append(bad, REPO, REF, "d2", "r1", b"{}", "sha256:s", "VERIFY", "t2")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_INVALID", exc
    else:
        raise AssertionError("appended to an invalid ledger")

    # An identical retry is a no-op only on a valid ledger that indexes it.
    corrupt = FakeGit()
    l.append(corrupt, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    corrupt.objects[corrupt.objects[corrupt.refs[REF]]["tree"]]["files"][l.LEDGER] = (
        b'{"seq":5}\n'
    )
    try:
        l.append(corrupt, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_INVALID", exc
    else:
        raise AssertionError("idempotent retry accepted on a corrupted ledger")
    undecodable = FakeGit()
    l.append(undecodable, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    undecodable.objects[undecodable.objects[undecodable.refs[REF]]["tree"]]["files"][
        l.LEDGER
    ] = b"\xff\n"
    try:
        l.append(undecodable, REPO, REF, "d2", "r1", b"{}", "sha256:s", "VERIFY", "t2")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_INVALID", exc
    else:
        raise AssertionError("appended to an undecodable ledger")
    # A ledger over the contents API's 1 MB inline limit comes back with no
    # content; it must never be read as empty and restarted at genesis.
    class Large(FakeGit):
        def __call__(self, method, path, payload):
            if method == "GET" and "contents/v1/ledger.jsonl" in path:
                return {"content": "", "encoding": "none"}
            return super().__call__(method, path, payload)

    large = Large()
    tip = large.refs[REF]
    try:
        l.append(large, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_UNAVAILABLE", exc
    else:
        raise AssertionError("an unreadable ledger was treated as empty")
    assert large.refs[REF] == tip, "the ref moved on an unreadable ledger"

    # A retry with the same receipt but a different subject or outcome collides.
    same = FakeGit()
    l.append(same, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    assert l.append(same, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t9") is None
    for changed in ({"subject_digest": "sha256:other"}, {"outcome": "BLOCK"}):
        args = {"subject_digest": "sha256:s", "outcome": "AUTHORIZE"} | changed
        try:
            l.append(same, REPO, REF, "d1", "r1", receipt, args["subject_digest"], args["outcome"], "t1")
        except l.LedgerError as exc:
            assert exc.code == "RECEIPT_COLLISION", exc
        else:
            raise AssertionError(f"retry with {changed} reported as recorded")

    # Line separators other than \n inside values never split an entry.
    sep = FakeGit()
    l.append(sep, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t\u2028x")
    assert l.append(sep, REPO, REF, "d2", "r1", b"{}", "sha256:s", "VERIFY", "t2")["seq"] == 1

    orphan = FakeGit()
    l.append(orphan, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
    orphan.objects[orphan.objects[orphan.refs[REF]]["tree"]]["files"][
        l.receipt_path("o", "r1")
    ] = b"{}"
    try:
        l.append(orphan, REPO, REF, "o", "r1", b"{}", "sha256:s", "VERIFY", "t2")
    except l.LedgerError as exc:
        assert exc.code == "LEDGER_INVALID", exc
    else:
        raise AssertionError("an orphaned receipt was treated as recorded")

    # Any provider failure is LEDGER_UNAVAILABLE, wherever it happens.
    class Flaky(FakeGit):
        def __init__(self, fail_on: str) -> None:
            super().__init__()
            self.fail_on = fail_on

        def __call__(self, method, path, payload):
            if self.fail_on in f"{method} {path}" and getattr(self, "armed", False):
                raise l.ApiError(502)
            return super().__call__(method, path, payload)

    for where in (
        "GET repos/o/r/contents/v1/receipts",
        "POST repos/o/r/git/trees",
        "PATCH",
    ):
        flaky = Flaky(where)
        l.append(flaky, REPO, REF, "d1", "r1", receipt, "sha256:s", "AUTHORIZE", "t1")
        flaky.armed = True
        try:
            l.append(flaky, REPO, REF, "d2", "r1", b"{}", "sha256:s", "VERIFY", "t2")
        except l.LedgerError as exc:
            assert exc.code == "LEDGER_UNAVAILABLE", (where, exc)
        else:
            raise AssertionError(f"provider failure at {where} was not reported")

    # Attack matrix (page 09): each attack against each anchor availability.
    lines = text.splitlines()
    head = json.loads(lines[-1])["entry_digest"]
    rs = receipts(git)
    middle_deleted = "\n".join([lines[0], lines[2]])
    tail_truncated = "\n".join(lines[:2])
    forged = l.entry(None, "x", "r1", b"{}", "sha256:s", "AUTHORIZE", "t")
    rewritten = l.canonical(forged).decode()
    rs_rewritten = {**rs, l.receipt_path("x", "r1"): b"{}"}
    assert l.verify(text, rs, (head,)) == []
    # Middle deletion breaks the chain even with no anchor.
    assert any("chain break" in f for f in l.verify(middle_deleted, rs))
    # A spliced entry with the right seq but a forged link (digest recomputed) breaks the chain.
    body = {k: v for k, v in json.loads(lines[1]).items() if k != "entry_digest"} | {
        "prev_entry_digest": "sha256:" + "f" * 64
    }
    spliced = body | {"entry_digest": l.digest(l.canonical(body))}
    assert any(
        "chain break" in f
        for f in l.verify(
            "\n".join([lines[0], l.canonical(spliced).decode(), lines[2]]), rs
        )
    )
    # Tail truncation and a full rewrite are invisible without an anchor...
    assert l.verify(tail_truncated, rs) == []
    assert l.verify(rewritten, rs_rewritten) == []
    # ...and detected while a merge trailer, unexpired check or owner copy names the head.
    assert any(
        "truncated or rewritten" in f for f in l.verify(tail_truncated, rs, (head,))
    )
    assert any(
        "truncated or rewritten" in f
        for f in l.verify(rewritten, rs_rewritten, (head,))
    )
    # A swapped receipt is caught by its digest.
    swapped = {**rs, l.receipt_path("d2", "r1"): b'{"w":"x"}'}
    assert any("digest mismatch" in f for f in l.verify(text, swapped))
    # A canonical entry with non-string identifiers is a ledger failure, not a crash.
    odd = {k: v for k, v in first.items() if k != "entry_digest"} | {"decision_id": 7}
    odd = odd | {"entry_digest": l.digest(l.canonical(odd))}
    assert any(
        "unsafe receipt identifiers" in f
        for f in l.verify(l.canonical(odd).decode(), {})
    )
    # F1: one immutable receipt revision may appear in the index only once.
    again = l.entry(
        first,
        "d1",
        "r1",
        receipt,
        "sha256:" + "1" * 64,
        "AUTHORIZE",
        "2026-10-20T00:00:01Z",
    )
    twice = l.canonical(first).decode() + "\n" + l.canonical(again).decode()
    assert any(
        "duplicate receipt revision d1/r1" in f
        for f in l.verify(twice, {l.receipt_path("d1", "r1"): receipt})
    )

    # Path identifiers cannot escape the receipts directory.
    try:
        l.receipt_path("../x", "r1")
    except l.LedgerError:
        pass
    else:
        raise AssertionError("unsafe receipt path accepted")

    # The Stage B drill itself, end to end against the fake provider.
    results = l.drill(FakeGit(), REPO, REF, "123")
    assert all(passed for _, passed, _ in results), results
    assert [s.split()[0] for s, _, _ in results] == [
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
        "L7",
        "L8",
    ]

    # D-20 topology check against the exact payloads the owner applies.
    drill_dir = HERE.parent / "drill" / "ledger"
    writer = json.loads((drill_dir / "writer-ruleset.json").read_text())
    integrity = json.loads((drill_dir / "integrity-ruleset.json").read_text())
    ref, app = "mandate-g0/ledger", 5336871
    assert l.ruleset_failures([writer, integrity], ref, app) == []
    assert l.ruleset_failures([writer], ref, app), "missing integrity ruleset passed"
    assert l.ruleset_failures([integrity], ref, app), "missing writer ruleset passed"
    app_bypass = {**integrity, "bypass_actors": writer["bypass_actors"]}
    assert l.ruleset_failures([writer, app_bypass], ref, app), (
        "App M bypassing integrity passed"
    )
    merged = {**writer, "rules": writer["rules"] + integrity["rules"]}
    assert l.ruleset_failures([merged], ref, app), "one combined ruleset passed"
    role = {
        **writer,
        "bypass_actors": writer["bypass_actors"]
        + [{"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}],
    }
    assert l.ruleset_failures([role, integrity], ref, app), (
        "an extra writer bypass passed"
    )
    assert l.ruleset_failures(
        [writer, {**integrity, "enforcement": "evaluate"}], ref, app
    ), "evaluate-only integrity passed"
    elsewhere = {
        **integrity,
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
    }
    assert l.ruleset_failures([writer, elsewhere], ref, app), (
        "integrity on another ref passed"
    )
    assert l.ruleset_failures([writer, integrity], ref, 1), "wrong App ID passed"

    # GitHub matches with FNM_PATHNAME: `*` stops at `/`, `**` crosses it.
    def on(r, pattern):
        return {**r, "conditions": {"ref_name": {"include": [pattern], "exclude": []}}}

    assert l.ruleset_failures(
        [on(writer, "refs/heads/*"), on(integrity, "refs/heads/*")], ref, app
    ), "`*` crossed a slash"
    assert (
        l.ruleset_failures(
            [on(writer, "refs/heads/**"), on(integrity, "refs/heads/mandate-g0/*")],
            ref,
            app,
        )
        == []
    )
    assert l.ruleset_failures([on(writer, "~ALL"), integrity], ref, app) == []

    # F2: teardown resolves exactly the two drill rulesets on the drill ref, or refuses.
    named = [{**writer, "id": 11}, {**integrity, "id": 12}]
    assert l.drill_ruleset_ids(named) == [11, 12]
    production = {**writer, "id": 13, "name": "mandate-ledger-writer"}
    assert l.drill_ruleset_ids(named + [production]) == [11, 12], (
        "a production ruleset was selected"
    )
    for broken in (
        named[:1],  # one missing
        named + [{**integrity, "id": 14}],  # duplicated name
        [
            named[0],
            {
                **named[1],
                "conditions": {
                    "ref_name": {"include": ["refs/heads/main"], "exclude": []}
                },
            },
        ],
        [
            named[0],
            {
                **named[1],
                "conditions": {
                    "ref_name": {
                        "include": ["refs/heads/mandate-g0/ledger", "refs/heads/main"],
                        "exclude": [],
                    }
                },
            },
        ],
    ):
        try:
            l.drill_ruleset_ids(broken)
        except l.LedgerError:
            pass
        else:
            raise AssertionError(f"teardown accepted {broken}")

    print("ledger tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
