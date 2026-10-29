"""Lifecycle checks. Run: python3 mandate/tests/test_lifecycle.py

The real reducer runs over canned workflow runs shaped like the REST API's
``actions/runs?head_sha=`` items. Nothing calls GitHub, and nothing here is
evidence that a live merge triggers anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import lifecycle as lc  # noqa: E402

MERGE = "1" * 40
RELEASE, APPLY = ".github/workflows/release-please.yml", ".github/workflows/infra-apply.yml"
PLAN = lc.plan("d-" + "a" * 64, "r2", MERGE, "R0", (RELEASE, APPLY), "2026-10-28T12:00:00Z")
BEFORE, AFTER, LATER = "2026-10-28T11:00:00Z", "2026-10-28T12:00:00Z", "2026-10-28T13:00:00Z"


def run(path: str, conclusion: str | None = "success", *, sha: str = MERGE, run_id: int = 1, attempt: int = 1) -> dict:
    status = "completed" if conclusion else "in_progress"
    return {"id": run_id, "run_attempt": attempt, "path": path, "head_sha": sha, "status": status, "conclusion": conclusion}


def states(log: list[dict]) -> list[str]:
    return [entry["state"] for entry in log]


def main() -> int:
    ok = [run(RELEASE), run(APPLY, run_id=2)]

    # The plan keys the obligations to the decision, its receipt revision and the merge.
    assert (PLAN["decision_id"], PLAN["receipt_revision"], PLAN["merge_sha"], PLAN["recovery"]) == (
        "d-" + "a" * 64, "r2", MERGE, "R0")

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
    empty = lc.plan("d-" + "a" * 64, "r2", MERGE, "R0", (), "2026-10-28T12:00:00Z")
    assert states(lc.reconcile(empty, [], [], BEFORE)[0]) == ["LIFECYCLE_OK"]

    print("lifecycle tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
