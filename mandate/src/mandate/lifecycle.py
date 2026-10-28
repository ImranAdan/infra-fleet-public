"""Lifecycle: after a merge, whether the configured GitHub follow-ups ran on
exactly that merge commit.

    MERGED -> DOWNSTREAM_TRIGGERED -> LIFECYCLE_OK | INCOMPLETE | UNKNOWN

plan() keys the obligations (workflow files expected to run on the merge
commit) to the decision ID, its receipt revision and the merge SHA, and
carries the class's recovery level: nothing here rolls back or reverts.
reconcile() is a pure reducer over the provider's workflow runs for that
commit. It appends to the log only when what it observes changes, so
duplicate and late observations never rewrite it, and LIFECYCLE_OK is final.
A late success after a deadline breach is appended after the breach.

An obligation is satisfied by a run of its workflow on the merge commit
whose latest attempt succeeded; a run on any other commit counts for nothing.
LIFECYCLE_OK means every obligation is satisfied, and says nothing about
runtime or deployment health. At the deadline a missing or failed obligation
is INCOMPLETE; a run still going, or runs that could not be read, are
UNKNOWN, never OK. INCOMPLETE and UNKNOWN notify the owner.

Inactive: nothing calls this yet. Times are ISO 8601 UTC strings ("...Z"),
compared as text.
"""

from __future__ import annotations

from typing import Any

FINAL = "LIFECYCLE_OK"
NOTIFY = ("INCOMPLETE", "UNKNOWN")


def plan(
    decision_id: str, receipt_revision: str, merge_sha: str, recovery: str, obligations: tuple[str, ...], deadline: str
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "receipt_revision": receipt_revision,
        "merge_sha": merge_sha,
        "recovery": recovery,
        "obligations": list(obligations),
        "deadline": deadline,
    }


def _status(plan: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, str]:
    """Each obligation: satisfied, pending, failed or missing."""
    latest: dict[int, dict[str, Any]] = {}
    for run in runs:
        if run["head_sha"] == plan["merge_sha"] and run["path"] in plan["obligations"]:
            kept = latest.get(run["id"])
            if kept is None or run["run_attempt"] > kept["run_attempt"]:
                latest[run["id"]] = run
    found = {}
    for path in plan["obligations"]:
        mine = [run for run in latest.values() if run["path"] == path]
        if any(run["conclusion"] == "success" for run in mine):
            found[path] = "satisfied"
        elif any(run["status"] != "completed" for run in mine):
            found[path] = "pending"
        else:
            found[path] = "failed" if mine else "missing"
    return found


def reconcile(
    plan: dict[str, Any], log: list[dict[str, Any]], runs: list[dict[str, Any]] | None, now: str
) -> tuple[list[dict[str, Any]], bool]:
    """(log, notify) after observing ``runs``: None when they could not be read."""
    if log and log[-1]["state"] == FINAL:
        return log, False
    found = {} if runs is None else _status(plan, runs)
    seen = set(found.values())
    if runs is None:
        state = "UNKNOWN"
    elif seen <= {"satisfied"}:
        state = FINAL
    elif now < plan["deadline"]:
        state = "DOWNSTREAM_TRIGGERED" if seen - {"missing"} else "MERGED"
    else:
        state = "INCOMPLETE" if seen & {"missing", "failed"} else "UNKNOWN"
    if log and (log[-1]["state"], log[-1]["obligations"]) == (state, found):
        return log, False
    return [*log, {"at": now, "state": state, "obligations": found}], state in NOTIFY
