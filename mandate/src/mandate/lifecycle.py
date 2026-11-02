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
Each log entry carries the latest attempt seen of every such run, across all
observations, so an older attempt reported later, or a run missing from a
later listing, never undoes what a newer attempt showed. A completed attempt
never reverts to running.
LIFECYCLE_OK means every obligation is satisfied, and says nothing about
runtime or deployment health. At the deadline a missing or failed obligation
is INCOMPLETE; a run still going, or runs that could not be read, are
UNKNOWN, never OK. INCOMPLETE and UNKNOWN notify the owner.

Records persist on the ledger branch, one per merge commit at
v1/lifecycle/<merge_sha>.json holding {"plan", "log"}, written by the same
compare-and-swap as receipts. ensure() saves a plan once: every worker
derives the same plan from the provider and the ledger (managed()), so
duplicate and recovering writers agree, and a record holding another plan is
LEDGER_INVALID, never satisfied. observe() reconciles one observation into
the stored log, so a restarted worker continues from its history and
watermarks, and only the writer that appends an INCOMPLETE or UNKNOWN entry
notifies.

Inactive: the executor ensures plans, but nothing observes yet. Times are ISO
8601 UTC strings ("...Z"), compared as text.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from mandate import ledger as l
from mandate.delegation import Delegation

FINAL = "LIFECYCLE_OK"
NOTIFY = ("INCOMPLETE", "UNKNOWN")
TIME = "%Y-%m-%dT%H:%M:%SZ"
WINDOW = timedelta(hours=1)  # ponytail: one deadline for every class; a per-class one when a class needs longer


def plan(
    decision_id: str,
    receipt_revision: str,
    merge_sha: str,
    recovery: dict[str, str | None],
    obligations: tuple[str, ...],
    deadline: str,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "receipt_revision": receipt_revision,
        "merge_sha": merge_sha,
        "recovery": recovery,
        "obligations": list(obligations),
        "deadline": deadline,
    }


def managed(
    receipt: dict[str, Any], revision: str, merge_sha: str, merged_at: str, delegation: Delegation
) -> dict[str, Any]:
    """The plan a managed merge starts: each class the receipt names keeps its
    recovery level, its obligations are the union of theirs, and it is due
    WINDOW after the provider's merge time. Only the delegation the receipt
    was decided under says which obligations were authorized."""
    if delegation.source != receipt["subject"]["policy"]:
        raise l.LedgerError(
            "CONTRACT_ERROR",
            f"lifecycle obligations need delegation {receipt['subject']['policy']}, not {delegation.source}",
        )
    classes = {c.id: c for c in delegation.classes}
    named = [classes[c] for c in receipt["decision"]["classes"]]
    due = (datetime.strptime(merged_at, TIME) + WINDOW).strftime(TIME)
    return plan(receipt["decision_id"], revision, merge_sha, {c.id: c.recovery for c in named},
                tuple(sorted({o for c in named for o in c.obligations})), due)


def _update(
    api: l.Api, repo: str, ref: str, plan: dict[str, Any], change: Callable[[dict[str, Any]], dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """(record, written) for ``plan`` after ``change``. A lost race re-reads
    and changes the newer record, as ledger.append() does. The nonce keeps
    two identical writes from being one commit, which would let both win."""
    path = f"v1/lifecycle/{plan['merge_sha']}.json"
    for _attempt in range(l.RETRIES):
        try:
            state = l.read(api, repo, ref)
            data = l._file(api, repo, path, state.tip)
            try:
                stored = {"plan": plan, "log": []} if data is None else json.loads(data)
                other = stored["plan"] != plan
            except (ValueError, TypeError, KeyError):
                other = True
            if other:
                raise l.LedgerError("LEDGER_INVALID", f"{path} holds another plan")
            new = change(stored)
            if data is not None and new == stored:
                return stored, False
            body = l.canonical(new)
            sha = l.candidate(api, repo, state, {path: body}, f"lifecycle: {plan['merge_sha']} {secrets.token_hex(8)}")
            try:
                l.advance(api, repo, ref, sha)
            except l.ApiError as exc:
                if exc.status in (409, 422):
                    continue  # lost the race: re-read and change again
                raise
            return new, True
        except l.ApiError as exc:
            raise l.LedgerError("LEDGER_UNAVAILABLE", str(exc)) from None
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"lost the ref race {l.RETRIES} times")


def ensure(api: l.Api, repo: str, ref: str, plan: dict[str, Any]) -> dict[str, Any]:
    """The stored record for ``plan``, saved when absent."""
    return _update(api, repo, ref, plan, lambda stored: stored)[0]


def observe(
    api: l.Api, repo: str, ref: str, plan: dict[str, Any], runs: list[dict[str, Any]] | None, now: str
) -> tuple[list[dict[str, Any]], bool]:
    """reconcile() against the stored log; notify only when this call appended
    an INCOMPLETE or UNKNOWN entry."""
    record, written = _update(
        api, repo, ref, plan, lambda stored: {"plan": plan, "log": reconcile(plan, stored["log"], runs, now)[0]}
    )
    return record["log"], written and record["log"][-1]["state"] in NOTIFY


def _latest(plan: dict[str, Any], known: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """``known`` updated with the obligation runs on the merge commit in ``runs``."""
    latest = dict(known)
    for run in runs:
        if run["head_sha"] == plan["merge_sha"] and run["path"] in plan["obligations"]:
            seen = {"attempt": run["run_attempt"], "path": run["path"], "status": run["status"],
                    "conclusion": run["conclusion"]}
            kept = latest.get(str(run["id"]))
            if kept is None or (seen["attempt"], seen["status"] == "completed") > (
                    kept["attempt"], kept["status"] == "completed"):
                latest[str(run["id"])] = seen
    return latest


def _status(plan: dict[str, Any], latest: dict[str, Any]) -> dict[str, str]:
    """Each obligation: satisfied, pending, failed or missing."""
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
    known = log[-1]["runs"] if log else {}
    latest = known if runs is None else _latest(plan, known, runs)
    found = {} if runs is None else _status(plan, latest)
    seen = set(found.values())
    if runs is None:
        state = "UNKNOWN"
    elif seen <= {"satisfied"}:
        state = FINAL
    elif now < plan["deadline"]:
        state = "DOWNSTREAM_TRIGGERED" if seen - {"missing"} else "MERGED"
    else:
        state = "INCOMPLETE" if seen & {"missing", "failed"} else "UNKNOWN"
    if log and (log[-1]["state"], log[-1]["obligations"], log[-1]["runs"]) == (state, found, latest):
        return log, False
    return [*log, {"at": now, "state": state, "obligations": found, "runs": latest}], state in NOTIFY
