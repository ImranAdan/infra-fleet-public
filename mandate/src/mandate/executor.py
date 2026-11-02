"""Executor: one wake for one pull request, from fresh provider state to at
most one exact-head merge.

    read the PR -> latest receipt -> decide -> (AUTHORIZE) mint a token ->
    decide again -> re-read the PR -> trailers() revalidates and records ->
    exact-head merge -> read the merge back

Every wake starts from provider state, never from an event payload or an
earlier decision, so duplicate, late and reordered wakes converge. The token
is minted only after an AUTHORIZE and only writes the merge, and the whole
subject is decided again once it exists, so nothing that changed while it was
minted is merged on the earlier decision. An expired token (401) is replaced
and the subject decided again.

A merged PR is settled by its merge commit's trailers, never by its head:
MERGED when they are this wake's, ALREADY_MERGED when they name another
recorded AUTHORIZE about this PR at its merged head (an earlier wake or a
competing worker), and UNMANAGED_MERGE otherwise. A merge whose response is
lost is settled by reading the provider back, never by asking again.

Both managed results ensure the merge's lifecycle plan before returning, so a
worker that dies between GitHub's merge and the plan is recovered by the next
wake, which finds ALREADY_MERGED and saves the same plan. MERGED versus
ALREADY_MERGED still says which wake merged; an unmanaged merge is never
planned.

Inactive: nothing calls this yet. The result is returned, not recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mandate import ledger as l
from mandate import lifecycle as lc
from mandate import receipt as r
from mandate.delegation import Delegation

# Refusals the final revalidation (trailers()) or the enforcement read name.
DRIFT = ("HEAD_CHANGED", "BASE_CHANGED", "ENFORCEMENT_DRIFT", "ENFORCEMENT_MISSING")
ATTEMPTS = 3


def _merged(provider: l.Api, ledger: l.Api, ledger_repo: str, ref: str, repository: str, number: int,
            pr: dict[str, Any], delegation: Delegation, mine: str = "") -> tuple[str, str]:
    """ALREADY_MERGED when the merge commit's trailers name an AUTHORIZE
    receipt in the ledger about this PR at its merged head, MERGED when they
    are also ``mine`` (this wake's trailers); else UNMANAGED_MERGE. Either
    managed result first ensures the plan that receipt's lifecycle starts."""
    sha = pr["merge_commit_sha"]
    named = r.parse_trailers(provider("GET", f"repos/{repository}/commits/{sha}", None)["commit"]["message"])
    if named:
        for entry, receipt in r._decisions(*r._verified(ledger, ledger_repo, ref)):
            s = receipt["subject"]
            if (entry["decision_id"], entry["receipt_digest"]) == (named["Mandate-Decision"], named["Mandate-Receipt-Digest"]) \
                    and (s["repository"], s["pull_request"], s["head_sha"]) == (repository, number, pr["head"]["sha"]) \
                    and entry["outcome"] == "AUTHORIZE":
                lc.ensure(ledger, ledger_repo, ref,
                          lc.managed(receipt, entry["receipt_revision"], sha, pr["merged_at"], delegation))
                return ("MERGED" if named == r.parse_trailers(mine) else "ALREADY_MERGED"), sha
    return "UNMANAGED_MERGE", sha


def execute(
    provider: l.Api,
    mint: Callable[[], l.Api],
    ledger: l.Api,
    ledger_repo: str,
    ref: str,
    repository: str,
    number: int,
    delegation: Delegation,
    evaluate: Callable[[dict[str, Any], str], dict[str, Any]],
    enforcement: Callable[[], str],
) -> tuple[str, str]:
    """(result, detail) for one wake. ``provider`` reads; ``mint()`` returns a
    transport holding a fresh merge-only token. ``evaluate(pr, enforcement)``
    is the receipt the adapter and decide() give for the PR as read, and
    ``enforcement()`` the enforcement snapshot digest (it raises
    ENFORCEMENT_MISSING when there is none)."""
    pull = f"repos/{repository}/pulls/{number}"
    for _attempt in range(ATTEMPTS):
        pr = provider("GET", pull, None)
        if pr["merged"]:
            return _merged(provider, ledger, ledger_repo, ref, repository, number, pr, delegation)
        if pr["state"] != "open":
            return "CLOSED", ""
        if delegation.mode != "enforce":
            return "SHADOW", "the delegation grants no merge"
        author = pr["user"]["login"]
        if delegation.identity_collision or author.casefold() not in {a.casefold() for a in delegation.agents}:
            return "PROPOSER_UNREGISTERED", author
        try:
            after = r.pr_latest(ledger, ledger_repo, ref, repository, number)
            fresh = evaluate(pr, enforcement())
            if fresh["decision"]["outcome"] == "AUTHORIZE":
                write = mint()
                fresh = evaluate(pr, enforcement())  # whatever changed while it was minted
            if fresh["decision"]["outcome"] != "AUTHORIZE":
                r.record(ledger, ledger_repo, ref, fresh, delegation, after=after)
                return "REFUSED", fresh["decision"]["outcome"]
            now = provider("GET", pull, None)
            subject = {**fresh["subject"], "head_sha": now["head"]["sha"], "base_sha": now["base"]["sha"],
                       "enforcement": enforcement()}
            message = r.trailers(ledger, ledger_repo, ref, subject, fresh, delegation, after=after)
        except l.LedgerError as exc:
            if exc.code == "STALE_DECISION":
                continue
            if exc.code in DRIFT:
                return exc.code, str(exc)
            raise
        try:
            write("PUT", f"{pull}/merge", {"sha": subject["head_sha"], "merge_method": "squash",
                                           "commit_title": f"Merge pull request #{number}", "commit_message": message})
        except l.ApiError as exc:
            if exc.status == 401:
                continue  # expired token: mint again and decide the whole subject again
            refused = str(exc)
        else:
            refused = ""
        done = provider("GET", pull, None)
        if not done["merged"]:
            return "NOT_MERGED", refused
        return _merged(provider, ledger, ledger_repo, ref, repository, number, done, delegation, message)
    return "UNAVAILABLE", f"no stable decision in {ATTEMPTS} attempts"
