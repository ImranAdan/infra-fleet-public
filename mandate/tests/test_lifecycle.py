"""Lifecycle checks. Run: python3 mandate/tests/test_lifecycle.py

The real reducer runs over canned workflow runs shaped like the REST API's
``actions/runs?head_sha=`` items, and its records persist through FakeGit,
the fast-forward-only ledger from test_ledger. Nothing calls GitHub, and
nothing here is evidence that a live merge triggers anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from test_ledger import REF, REPO, FakeGit  # noqa: E402

from mandate import ledger as l  # noqa: E402
from mandate import lifecycle as lc  # noqa: E402

MERGE = "1" * 40
RELEASE, APPLY = ".github/workflows/release-please.yml", ".github/workflows/infra-apply.yml"
PLAN = lc.plan("d-" + "a" * 64, "r2", MERGE, {"dependency-manifest": "R0"}, (RELEASE, APPLY), "2026-10-28T12:00:00Z")
BEFORE, AFTER, LATER = "2026-10-28T11:00:00Z", "2026-10-28T12:00:00Z", "2026-10-28T13:00:00Z"


def run(path: str, conclusion: str | None = "success", *, sha: str = MERGE, run_id: int = 1, attempt: int = 1) -> dict:
    status = "completed" if conclusion else "in_progress"
    return {"id": run_id, "run_attempt": attempt, "path": path, "head_sha": sha, "status": status, "conclusion": conclusion}


def states(log: list[dict]) -> list[str]:
    return [entry["state"] for entry in log]


def stored(git: FakeGit) -> dict[str, dict]:
    return {p: json.loads(b) for p, b in git.files(REF).items() if p.startswith("v1/lifecycle/")}


def main() -> int:
    ok = [run(RELEASE), run(APPLY, run_id=2)]

    # The plan keys the obligations to the decision, its receipt revision and the merge.
    assert (PLAN["decision_id"], PLAN["receipt_revision"], PLAN["merge_sha"], PLAN["recovery"]) == (
        "d-" + "a" * 64, "r2", MERGE, {"dependency-manifest": "R0"})

    # Nothing observed yet; then a run started; then every obligation satisfied.
    log, _ = lc.reconcile(PLAN, [], [], BEFORE)
    log, _ = lc.reconcile(PLAN, log, [run(RELEASE, None)], BEFORE)
    log, notify = lc.reconcile(PLAN, log, ok, BEFORE)
    assert (states(log), notify) == (["MERGED", "DOWNSTREAM_TRIGGERED", "LIFECYCLE_OK"], False), states(log)

    # The same observation again changes nothing and never regresses.
    assert lc.reconcile(PLAN, log, ok, LATER) == (log, False)
    assert lc.reconcile(PLAN, log, None, LATER) == (log, False)  # OK is final

    # A run for another commit cannot satisfy an obligation.
    log, notify = lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, sha="2" * 40, run_id=2)], AFTER)
    assert (states(log), notify) == (["INCOMPLETE"], True), states(log)
    assert log[-1]["obligations"] == {RELEASE: "satisfied", APPLY: "missing"}, log[-1]

    # A failure at the deadline is INCOMPLETE; a later successful re-run appends
    # LIFECYCLE_OK and keeps the breach.
    log, _ = lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, "failure", run_id=2)], AFTER)
    log, notify = lc.reconcile(PLAN, log, [run(RELEASE), run(APPLY, "success", run_id=2, attempt=2)], LATER)
    assert (states(log), notify) == (["INCOMPLETE", "LIFECYCLE_OK"], False), states(log)

    # Observing the same breach again neither appends nor notifies the owner again.
    breach = [run(RELEASE), run(APPLY, "failure", run_id=2)]
    log, _ = lc.reconcile(PLAN, [], breach, AFTER)
    assert lc.reconcile(PLAN, log, breach, LATER) == (log, False)

    # An older attempt reported late does not undo the newer one.
    newer = [run(RELEASE), run(APPLY, "success", run_id=2, attempt=2), run(APPLY, "failure", run_id=2, attempt=1)]
    assert states(lc.reconcile(PLAN, [], newer, AFTER)[0]) == ["LIFECYCLE_OK"]

    # The latest attempt seen of each run is kept across observations, so an
    # older attempt reported later, alone, never satisfies a newer failed one...
    failed2 = [run(RELEASE), run(APPLY, "failure", run_id=2, attempt=2)]
    stale1 = [run(RELEASE), run(APPLY, "success", run_id=2, attempt=1)]
    log, notify = lc.reconcile(PLAN, [], failed2, AFTER)
    assert (states(log), notify) == (["INCOMPLETE"], True), states(log)
    assert log[-1]["runs"]["2"] == {"attempt": 2, "path": APPLY, "status": "completed", "conclusion": "failure"}, log[-1]
    assert lc.reconcile(PLAN, log, stale1, LATER) == (log, False)
    # ...or a newer one still running, before and at the deadline.
    log, _ = lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, None, run_id=2, attempt=2)], BEFORE)
    assert lc.reconcile(PLAN, log, stale1, BEFORE) == (log, False)
    assert states(lc.reconcile(PLAN, log, stale1, AFTER)[0]) == ["DOWNSTREAM_TRIGGERED", "UNKNOWN"]
    # A run missing from a later observation is still known.
    assert states(lc.reconcile(PLAN, log, [run(RELEASE)], AFTER)[0]) == ["DOWNSTREAM_TRIGGERED", "UNKNOWN"]
    # An unreadable provider forgets nothing.
    unread, _ = lc.reconcile(PLAN, log, None, AFTER)
    assert states(lc.reconcile(PLAN, unread, stale1, LATER)[0])[-1] == "UNKNOWN"
    # Each newer attempt seen is recorded, even when the state stays the same.
    log, _ = lc.reconcile(PLAN, log, [run(RELEASE), run(APPLY, None, run_id=2, attempt=3)], BEFORE)
    assert states(log) == ["DOWNSTREAM_TRIGGERED", "DOWNSTREAM_TRIGGERED"] and log[-1]["runs"]["2"]["attempt"] == 3, log
    assert lc.reconcile(PLAN, log, [run(RELEASE), run(APPLY, "success", run_id=2, attempt=2)], BEFORE) == (log, False)
    # A completed attempt never reverts to running.
    log, _ = lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, "failure", run_id=2)], AFTER)
    assert lc.reconcile(PLAN, log, [run(RELEASE), run(APPLY, None, run_id=2)], LATER) == (log, False)
    # A genuinely newer attempt still resolves the breach.
    log, _ = lc.reconcile(PLAN, [], failed2, AFTER)
    log, notify = lc.reconcile(PLAN, log, [run(APPLY, "success", run_id=2, attempt=3)], LATER)
    assert (states(log), notify) == (["INCOMPLETE", "LIFECYCLE_OK"], False), states(log)

    # Still running at the deadline is not definitive: UNKNOWN, as is a provider
    # that could not be read. Neither is ever OK.
    log, notify = lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, None, run_id=2)], AFTER)
    assert (states(log), notify) == (["UNKNOWN"], True), states(log)
    log, notify = lc.reconcile(PLAN, [], None, BEFORE)
    assert (states(log), notify) == (["UNKNOWN"], True), states(log)
    assert states(lc.reconcile(PLAN, [], None, AFTER)[0]) == ["UNKNOWN"]

    # Before the deadline a missing or failed obligation may still be satisfied.
    assert states(lc.reconcile(PLAN, [], [run(RELEASE), run(APPLY, "failure", run_id=2)], BEFORE)[0]) == [
        "DOWNSTREAM_TRIGGERED"]

    # No configured obligation: nothing to observe, so OK at once.
    empty = lc.plan("d-" + "a" * 64, "r2", MERGE, {}, (), "2026-10-28T12:00:00Z")
    assert states(lc.reconcile(empty, [], [], BEFORE)[0]) == ["LIFECYCLE_OK"]

    # Storage: one record per merge commit on the ledger branch, written by
    # compare-and-swap. Ensuring it again writes nothing.
    git = FakeGit()
    assert lc.ensure(git, REPO, REF, PLAN) == {"plan": PLAN, "log": []}
    tip = git.refs[REF]
    assert lc.ensure(git, REPO, REF, PLAN) == {"plan": PLAN, "log": []} and git.refs[REF] == tip
    assert stored(git) == {f"v1/lifecycle/{MERGE}.json": {"plan": PLAN, "log": []}}
    # Two workers ensuring the same plan at once leave one record.
    git = FakeGit()
    git.before_advance = lambda: lc.ensure(git, REPO, REF, PLAN)
    assert lc.ensure(git, REPO, REF, PLAN) == {"plan": PLAN, "log": []}
    assert list(stored(git)) == [f"v1/lifecycle/{MERGE}.json"]

    # A restarted worker continues from the stored log: the same or a stale
    # observation appends nothing and notifies no one, and a newer attempt
    # still resolves the breach, keeping it.
    git = FakeGit()
    lc.ensure(git, REPO, REF, PLAN)
    log, notify = lc.observe(git, REPO, REF, PLAN, failed2, AFTER)
    assert (states(log), notify) == (["INCOMPLETE"], True), states(log)
    assert lc.observe(git, REPO, REF, PLAN, failed2, LATER) == (log, False)
    assert lc.observe(git, REPO, REF, PLAN, stale1, LATER) == (log, False)
    log, notify = lc.observe(git, REPO, REF, PLAN, [run(APPLY, "success", run_id=2, attempt=3)], LATER)
    assert (states(log), notify) == (["INCOMPLETE", "LIFECYCLE_OK"], False), states(log)
    assert stored(git)[f"v1/lifecycle/{MERGE}.json"] == {"plan": PLAN, "log": log}
    # So does one restarted during UNKNOWN.
    git = FakeGit()
    log, notify = lc.observe(git, REPO, REF, PLAN, None, AFTER)
    assert (states(log), notify) == (["UNKNOWN"], True), states(log)
    assert lc.observe(git, REPO, REF, PLAN, None, LATER) == (log, False)
    # Two workers observing the same breach at once: one entry, one notice.
    git = FakeGit()
    lc.ensure(git, REPO, REF, PLAN)
    notices = []
    git.before_advance = lambda: notices.append(lc.observe(git, REPO, REF, PLAN, failed2, AFTER)[1])
    log, notify = lc.observe(git, REPO, REF, PLAN, failed2, AFTER)
    assert (states(log), notices + [notify]) == (["INCOMPLETE"], [True, False]), (states(log), notices, notify)

    # A record for another plan at this merge never satisfies this one.
    other = lc.plan("d-" + "b" * 64, "r1", MERGE, {}, (), "2026-10-28T12:00:00Z")
    git = FakeGit()
    assert states(lc.observe(git, REPO, REF, other, [], BEFORE)[0]) == ["LIFECYCLE_OK"]
    for name, call in (("ensure", lambda: lc.ensure(git, REPO, REF, PLAN)),
                       ("observe", lambda: lc.observe(git, REPO, REF, PLAN, ok, BEFORE))):
        try:
            call()
        except l.LedgerError as exc:
            assert exc.code == "LEDGER_INVALID", (name, exc)
        else:
            raise AssertionError(f"{name} accepted another plan's record")

    print("lifecycle tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
