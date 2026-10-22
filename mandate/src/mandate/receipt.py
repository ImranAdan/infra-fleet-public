"""Receipts: one versioned record per decision revision, kept in the ledger.

A ``decision_id`` names the immutable subject: repository, pull request,
head, base, delegation revision and enforcement snapshot. Any drift is a new
ID. Under one ID, receipts are revisions r1, r2, ...: every evaluation
record() accepts is the next revision, even one that means the same as the
last (a no-op would leave no trace for the staleness check), and flipping back
to an earlier result is a new revision, never a reuse.

reconcile_check() is the only check publisher: it shows the ledger's latest
revision, and publishers run as one serialized job per head commit. Recording
needs no group: ledger appends are compare-and-swap, and record() refuses a
decision whose PR gained a receipt after it read its inputs (``after``).

The merge commit is the anchor: trailers() records a fresh AUTHORIZE decision
for the subject the worker acted on and names that latest revision's receipt
digest and chain head. audit() checks a ledger against those anchors offline and says
literally what it cannot see. The anchor is repository-local, not an
independent transparency log: an owner or bypass actor who rewrites history,
or a key holder who appends after the last anchor, is a residual risk that
audit() reports as "not detectable with available anchor".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from mandate import ledger as l
from mandate.decision import REGISTRY, REGISTRY_VERSION, Decision, worst
from mandate.delegation import Delegation, fetch
from mandate.evidence import EvidenceRecord, Subject, evaluate

SCHEMA_VERSION = 1
DECISION_ID = re.compile(r"d-[0-9a-f]{64}")  # fullmatch; other ledger records (drills) differ
CHECK_NAME = "mandate/decision"  # the required check: live decisions only
SHADOW_CHECK_NAME = "mandate/shadow"  # never required; GitHub counts neutral as passing
SHADOW = "shadow"  # the enforcement snapshot of a decision that grants nothing
LIVE = re.compile(r"sha256:[0-9a-f]{64}")  # a real enforcement snapshot digest (fullmatch)
# One check publisher per head commit (checks belong to a commit, not a PR):
# publishers are workflows called with a ``head_sha`` input, so every caller
# computes this group.
CANONICAL_GROUP = "mandate-decision-${{ github.repository }}-${{ inputs.head_sha }}"
# The supported publisher step (main() below), as a recorder's follower must run it.
_RECONCILE = re.compile(r"PYTHONPATH=mandate/src python3 -m mandate\.receipt reconcile(?: [^;&|<>`()\n\\]+)?")
_ALWAYS = ("always()", "${{always()}}")
_USES_RECEIPTS = re.compile(r"mandate(\.| import )receipt|src/mandate/receipt\.py")
TRAILERS = ("Mandate-Decision", "Mandate-Receipt-Digest", "Mandate-Chain-Head")
_TRAILER = re.compile(rf"(?m)^({'|'.join(TRAILERS)}): (\S+)$")
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


def _verified(api: l.Api, repo: str, ref: str) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """(entries, receipts) from a verified ledger."""
    try:
        state = l.read(api, repo, ref)
        stored = l._receipts(api, repo, state)
    except l.ApiError as exc:
        raise l.LedgerError("LEDGER_UNAVAILABLE", str(exc)) from None
    failures = l.verify(state.text, stored)
    if failures:
        raise l.LedgerError("LEDGER_INVALID", "; ".join(failures))
    return [json.loads(x) for x in l._lines(state.text)], stored


def _decisions(entries: list[dict[str, Any]], stored: dict[str, bytes]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every decision's (entry, receipt), each exactly schema v1 and bound to
    its index entry; anything else is LEDGER_INVALID. Other records (the
    drill's share the ledger) are skipped."""
    decisions = []
    for entry in entries:
        if not DECISION_ID.fullmatch(entry["decision_id"]):
            continue
        name = f"{entry['decision_id']}/{entry['receipt_revision']}"
        try:
            receipt = json.loads(stored[l.receipt_path(entry["decision_id"], entry["receipt_revision"])])
        except ValueError:
            raise l.LedgerError("LEDGER_INVALID", f"receipt {name} is not JSON") from None
        if not isinstance(receipt, dict) or not _well_formed(receipt):
            raise l.LedgerError("LEDGER_INVALID", f"receipt {name} is malformed or of an unsupported schema")
        # The index orders decisions and the receipt carries them: they must agree.
        if (entry["decision_id"], entry["receipt_revision"], entry["subject_digest"], entry["outcome"]) != (
            receipt["decision_id"], receipt.get("receipt_revision"), receipt["subject_digest"], receipt["decision"]["outcome"]
        ):
            raise l.LedgerError("LEDGER_INVALID", f"receipt {name} does not match its index entry")
        decisions.append((entry, receipt))
    return decisions


def _pr_latest(entries: list[dict[str, Any]], stored: dict[str, bytes], repository: str, pull_request: int) -> str | None:
    found = None
    for entry, receipt in _decisions(entries, stored):
        if (receipt["subject"]["repository"], receipt["subject"]["pull_request"]) == (repository, pull_request):
            found = entry["entry_digest"]
    return found


def pr_latest(api: l.Api, repo: str, ref: str, repository: str, pull_request: int) -> str | None:
    """Entry digest of the PR's latest receipt, or None. A recorder reads it
    before the state it decides from and passes it to record() as ``after``."""
    return _pr_latest(*_verified(api, repo, ref), repository, pull_request)


def record(
    api: l.Api,
    repo: str,
    ref: str,
    receipt: dict[str, Any],
    delegation: Delegation | None = None,
    *,
    after: str | None,
) -> tuple[dict[str, Any], str, bool]:
    """(ledger entry for this decision's latest revision, chain head, appended).

    ``delegation`` is the pinned delegation the decision was taken under; an
    AUTHORIZE is recorded only if it holds under it (_authorized).

    ``after`` is pr_latest() as read before the decision's inputs. Recorders
    run outside any concurrency group, so they can finish out of order: if
    the PR gained a receipt since, this decision may be stale and is refused
    with STALE_DECISION (decide again), atomically with the append. So the
    ledger orders each PR's receipts by when their inputs were read."""
    did = receipt.get("decision_id")
    if not isinstance(receipt, dict) or not _well_formed(receipt):
        raise l.LedgerError("CONTRACT_ERROR", f"receipt for {did} is not exactly schema v{SCHEMA_VERSION}")
    if delegation is not None and delegation.source != receipt["subject"]["policy"]:
        raise l.LedgerError("CONTRACT_ERROR", f"receipt for {did} was decided under another delegation")
    if receipt["decision"]["outcome"] == "AUTHORIZE" and not _authorized(receipt, delegation):
        raise l.LedgerError("CONTRACT_ERROR", f"AUTHORIZE for {did} does not hold under its delegation")
    for _attempt in range(l.RETRIES):
        entries, stored = _verified(api, repo, ref)
        mine = [x for x in entries if x["decision_id"] == did]
        s = receipt["subject"]
        revision = f"r{len(mine) + 1}"

        def unchanged(index: str, receipts: dict[str, bytes]) -> None:
            entries_now = [json.loads(line) for line in index.splitlines() if line]
            now = _pr_latest(entries_now, receipts, s["repository"], s["pull_request"])
            if now != after:
                raise l.LedgerError("STALE_DECISION", f"PR {s['pull_request']} has a newer receipt than {did} saw: decide again")

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
                unchanged,
            )
        except l.LedgerError as exc:
            if exc.code == "RECEIPT_COLLISION":
                continue  # a concurrent writer took this revision: re-read
            raise
        if item is not None:
            return item, item["entry_digest"], True
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"lost the revision race {l.RETRIES} times")


def _runs(api: l.Api, repo: str, head: str, name: str, app_id: int) -> list[dict[str, Any]]:
    """Every run named ``name`` on ``head`` created by the publisher App."""
    runs: list[dict[str, Any]] = []
    for page in range(1, 1000):  # filter=all: the default lists only the newest run
        data = api(
            "GET",
            f"repos/{repo}/commits/{head}/check-runs?check_name={quote(name)}"
            f"&filter=all&per_page=100&page={page}",
            None,
        )
        runs += data["check_runs"]
        if not data["check_runs"] or len(runs) >= data["total_count"]:
            break
    return [x for x in runs if (x.get("app") or {}).get("id") == app_id]


def _show(
    api: l.Api,
    repo: str,
    name: str,
    receipt: dict[str, Any],
    entry: dict[str, Any],
    chain_head: str,
    app_id: int,
    prs: list[int],
) -> None:
    """Make every run of ours named ``name`` on the head show this revision,
    whichever decision ID it showed before.

    The shadow check is always neutral. The required check passes only for a
    live sha256 snapshot that AUTHORIZEs for a single PR (``prs``: every PR
    with a decision on this head, since a check belongs to the commit); a
    shadow decision there only fails runs that already exist."""
    head, did = receipt["subject"]["head_sha"], receipt["decision_id"]
    outcome, revision = receipt["decision"]["outcome"], entry["receipt_revision"]
    # From the recorded snapshot, never a caller flag: only a live sha256
    # snapshot can pass, shadow is neutral, anything else fails closed.
    enforcement = receipt["subject"]["enforcement"]
    shadow = enforcement == SHADOW
    passes = outcome == "AUTHORIZE" and bool(LIVE.fullmatch(enforcement)) and len(prs) == 1
    if name == SHADOW_CHECK_NAME:
        conclusion = "neutral"
    else:
        conclusion = "success" if passes else "failure"
    reasons = "".join(
        f"\n- `{x['code']}` ({x['outcome']}, {x['owner']}): {x['detail'][:200]}"
        for x in receipt["decision"]["reasons"]
    )
    summary = (
        f"Receipt `{did}/{revision}`, digest `{entry['receipt_digest']}`, "
        f"chain head `{chain_head}`."
        + (" Shadow mode: this decision grants nothing." if shadow else "")
        + (f" Head shared by PRs {', '.join(f'#{n}' for n in prs)}: one check cannot represent them all." if len(prs) > 1 else "")
        + reasons
    )
    encoded = summary.encode("utf-8")
    if len(encoded) > SUMMARY_LIMIT:  # bytes, cut on a character boundary
        cut = "\n- … more reasons in the receipt"
        keep = encoded[: SUMMARY_LIMIT - len(cut.encode("utf-8"))]
        summary = keep.decode("utf-8", "ignore") + cut
    payload = {
        "name": name,
        "external_id": did,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": f"{outcome} ({revision})"  # GitHub caps titles at 255 characters
            + (f", head shared by {len(prs)} PRs" if len(prs) > 1 else "")
            + (", shadow: grants nothing" if shadow and name == CHECK_NAME else ""),
            "summary": summary,
        },
    }
    mine = _runs(api, repo, head, name, app_id)
    if not mine and not (shadow and name == CHECK_NAME):  # never open a required run for shadow
        api("POST", f"repos/{repo}/check-runs", {**payload, "head_sha": head})
    for run in mine:  # a past race or an older decision ID; each must show this
        shown = run.get("output") or {}
        if run.get("conclusion") != conclusion or any(
            shown.get(k) != v for k, v in payload["output"].items()
        ):  # GitHub adds text and annotation fields we never send
            api("PATCH", f"repos/{repo}/check-runs/{run['id']}", payload)


_RECEIPT_KEYS = {"schema_version", "decision_id", "subject", "subject_digest", "decision",
                 "versions", "actors", "evaluated_at"}  # + receipt_revision once recorded
_SUBJECT_KEYS = {"repository", "pull_request", "head_sha", "base_sha", "policy", "enforcement"}
_DECISION_KEYS = {"registry_version", "outcome", "reasons", "classes", "accepted", "policy", "subject"}
_REASON_KEYS = {"code", "outcome", "owner", "detail"}


def _records(accepted: Any) -> list[EvidenceRecord] | None:
    """The accepted evidence as records, or None if it is not the shape decide() emits."""
    if not isinstance(accepted, list):
        return None
    found = []
    for item in accepted:
        if not (isinstance(item, dict) and set(item) == {"requirement", "records"}
                and isinstance(item["requirement"], str) and isinstance(item["records"], list)):
            return None
        for raw in item["records"]:
            try:
                found.append(EvidenceRecord.from_dict(raw))
            except (ValueError, TypeError, AttributeError):
                return None
    return found


def _well_formed(receipt: dict[str, Any]) -> bool:
    """Exactly schema v1 as build() and Decision.to_dict() emit it: every key
    present at its type, no other key, a supported registry version, a
    decision decide() could produce from its reasons, and an identity that is
    its subject's."""
    revision = receipt.get("receipt_revision")
    subject, decision = receipt.get("subject"), receipt.get("decision")
    if not (
        set(receipt) - {"receipt_revision"} == _RECEIPT_KEYS
        and (revision is None or (isinstance(revision, str) and l.ID.fullmatch(revision)))
        and type(receipt["schema_version"]) is int and receipt["schema_version"] == SCHEMA_VERSION
        and isinstance(receipt["decision_id"], str)
        and isinstance(receipt["evaluated_at"], str)
        and all(isinstance(receipt[k], dict) and all(isinstance(x, str) for x in receipt[k]) for k in ("versions", "actors"))
        and isinstance(subject, dict) and set(subject) == _SUBJECT_KEYS
        and all(isinstance(subject[k], str) for k in _SUBJECT_KEYS - {"pull_request"})
        and type(subject["pull_request"]) is int
        and isinstance(decision, dict) and set(decision) == _DECISION_KEYS
        and type(decision["registry_version"]) is int and decision["registry_version"] == REGISTRY_VERSION
        and isinstance(decision["outcome"], str)
        and isinstance(decision["classes"], list) and all(isinstance(c, str) for c in decision["classes"])
        and _records(decision["accepted"]) is not None
        and isinstance(decision["reasons"], list)
        and all(isinstance(x, dict) and set(x) == _REASON_KEYS and all(isinstance(x[k], str) for k in _REASON_KEYS)
                for x in decision["reasons"])
    ):
        return False
    return (
        # What decide() could have produced: registered reasons with their
        # registered outcome and owner, and the outcome is the worst of them.
        all(REGISTRY.get(x["code"].split(":", 1)[0]) == (x["outcome"], x["owner"]) for x in decision["reasons"])
        and decision["outcome"] == worst([x["outcome"] for x in decision["reasons"]])
        # Its identity is its subject: the ID and digest recompute from it, and
        # the decision inside is about the same head, base and policy.
        and receipt["subject_digest"] == l.digest(l.canonical(subject))
        and receipt["decision_id"] == "d-" + receipt["subject_digest"].removeprefix("sha256:")
        and decision["subject"] == {k: subject[k] for k in ("repository", "head_sha", "base_sha", "policy")}
        and decision["policy"] == subject["policy"]
    )


def _authorized(receipt: dict[str, Any], delegation: Delegation | None) -> bool:
    """Whether an AUTHORIZE holds under the pinned delegation it names.

    decide() authorizes only through the delegation's authorizing classes, and
    those must require evidence. So the classes must be authorizing classes of
    exactly this delegation (its source is the receipt's policy), the accepted
    requirements exactly what they require, and re-evaluating the claimed
    records with the production evidence rules (producer, App, workflow,
    event, subject binding) must accept exactly them. Whether the delegation
    should have matched the PR's findings needs the inputs: historical replay
    (KAN-27). Whether the check runs exist is the producer's word, as in
    decide().
    """
    subject, decision = receipt["subject"], receipt["decision"]
    if delegation is None or (delegation.source, delegation.repository) != (subject["policy"], subject["repository"]):
        return False
    if LIVE.fullmatch(subject["enforcement"]) and delegation.mode != "enforce":
        return False  # a shadow-mode delegation grants no merge authority
    authorize = {c.id: c for c in delegation.classes if c.decide == "authorize"}
    classes = decision["classes"]
    if not classes or any(c not in authorize for c in classes):
        return False
    required = tuple(sorted({name for c in classes for name in authorize[c].require}))
    records = _records(decision["accepted"]) or []
    about = Subject(subject["repository"], subject["head_sha"], subject["base_sha"], subject["policy"])
    found = evaluate(delegation, required, records, about)
    accepted = [{"requirement": n, "records": [r.to_dict() for r in rs]} for n, rs in found.accepted]
    return not found.failures and accepted == decision["accepted"]


def _newest(
    entries: list[dict[str, Any]], stored: dict[str, bytes], repo: str, head: str, open_prs: dict[int, Any]
) -> dict[str, tuple[dict[str, Any], dict[str, Any], list[int]]]:
    """Check name -> (entry, receipt, PRs) to show for this head.

    PRs: every open PR whose current head is this commit (``open_prs``, PR ->
    its current base), decided or not, since they all share the commit's one
    check. Candidates: their decisions on this head and their current base,
    where it is still their latest decision. The required check follows the newest
    of their decisions in any mode, so a shadow decision that supersedes a
    live one retires it; the shadow check follows the newest shadow one.
    """
    decisions = [(e, rc) for e, rc in _decisions(entries, stored) if rc["subject"]["repository"] == repo]
    latest = {receipt["subject"]["pull_request"]: receipt for _, receipt in decisions}
    prs = sorted(open_prs)
    current = {
        pr
        for pr, receipt in latest.items()
        if pr in open_prs and (receipt["subject"]["head_sha"], receipt["subject"]["base_sha"]) == (head, open_prs[pr])
    }
    found: dict[str, tuple[dict[str, Any], dict[str, Any], list[int]]] = {}
    for entry, receipt in decisions:
        s = receipt["subject"]
        if s["head_sha"] == head and s["pull_request"] in current:
            names = [CHECK_NAME] + ([SHADOW_CHECK_NAME] if s["enforcement"] == SHADOW else [])
            for name in names:
                found[name] = (entry, receipt, prs)
    return found


def reconcile_check(
    api: l.Api,
    repo: str,
    ref: str,
    head: str,
    *,
    app_id: int,
    delegations: Callable[[str, str], Delegation],
) -> dict[str, dict[str, Any]]:
    """Show the newest decision recorded for a head commit on its check.

    The only check publisher. The caller names the head, never a decision or
    revision, so a delayed caller cannot choose a superseded one, including an
    older decision ID for the same head (base, policy or enforcement moved).
    A decision is current only at its PR's live base: a moved or retargeted
    base fails closed until a decision there.
    The required ``mandate/decision`` follows the newest decision of any mode
    and passes only for a live AUTHORIZE; shadow decisions show on
    ``mandate/shadow`` (GitHub counts neutral as passing, so never on the
    required name) and fail any required run they supersede. Checks belong to
    a commit, so decisions from two PRs on one head fail closed.

    The Checks API has no compare-and-swap, so two boundaries hold the checks
    to the ledger:

    - one publisher per head commit: every job that can write checks runs in
      CANONICAL_GROUP (job-level) without cancelling in progress, and no job
      that can record waits in a group, where GitHub could replace it while
      pending (serial_violations() enforces both over the workflows);
    - if the ledger or the open PRs moved while this ran (recorders run
      outside the group), it shows the newer decision before returning. A
      recorder queues a reconcile after its append, so a later reconcile
      always reads it.

    Only runs created by ``app_id`` (the publisher App) are ours. The
    conclusion follows the receipt's recorded enforcement, and a passing one
    needs the AUTHORIZE to hold under its pinned delegation, which
    ``delegations(repository, policy)`` resolves. If anything stops
    it showing the current decision (an unreadable ledger or receipt, a
    provider error, nothing recorded for the head, any surprise), every
    required run of ours on the head fails before the error is raised. Returns check name -> the ledger entry it
    left on display.
    """
    try:
        return _reconcile(api, repo, ref, head, app_id, delegations)
    except Exception as exc:  # any failure to show the current decision fails closed
        _fail_closed(api, repo, head, app_id, exc)
        raise


def _fail_closed(api: l.Api, repo: str, head: str, app_id: int, exc: Exception) -> None:
    """The ledger can't say what is current: fail every required run of ours
    on this head, so an earlier success never outlives it. Best effort: if the
    provider is down too, the original error is what the caller sees."""
    payload = {
        "name": CHECK_NAME,
        "status": "completed",
        "conclusion": "failure",
        "output": {"title": getattr(exc, "code", type(exc).__name__), "summary": str(exc)[:1000]},
    }
    try:
        for run in _runs(api, repo, head, CHECK_NAME, app_id):
            if run.get("conclusion") != "failure" or (run.get("output") or {}).get("title") != payload["output"]["title"]:
                api("PATCH", f"repos/{repo}/check-runs/{run['id']}", payload)
    except (l.ApiError, KeyError, TypeError):
        pass


def _open_prs(api: l.Api, repo: str, head: str) -> dict[int, Any]:
    """Open PR -> current base SHA, for PRs whose current head is this commit.
    GitHub lists PRs associated with a commit, not only those it still heads,
    so filter on head.sha. A missing base is None, which no receipt names."""
    found: dict[int, Any] = {}
    for page in range(1, 1000):
        batch = api("GET", f"repos/{repo}/commits/{head}/pulls?per_page=100&page={page}", None)
        found |= {
            p["number"]: (p.get("base") or {}).get("sha")
            for p in batch
            if p.get("state") == "open" and (p.get("head") or {}).get("sha") == head
        }
        if len(batch) < 100:
            return found
    return found


def _reconcile(
    api: l.Api, repo: str, ref: str, head: str, app_id: int, delegations: Callable[[str, str], Delegation]
) -> dict[str, dict[str, Any]]:
    for _attempt in range(l.RETRIES):
        entries, stored = _verified(api, repo, ref)
        open_prs = _open_prs(api, repo, head)
        shown = _newest(entries, stored, repo, head, open_prs)
        if not shown:
            raise l.LedgerError("CONTRACT_ERROR", f"no receipt recorded for {repo}@{head} at its PR's current base")
        for name, (entry, receipt, prs) in shown.items():
            s = receipt["subject"]
            live = receipt["decision"]["outcome"] == "AUTHORIZE" and LIVE.fullmatch(s["enforcement"])
            if name == CHECK_NAME and live and not _authorized(receipt, delegations(repo, s["policy"])):
                # Never pass a required check on an AUTHORIZE its delegation does not support.
                raise l.LedgerError("LEDGER_INVALID", f"AUTHORIZE {entry['decision_id']} does not hold under its delegation")
            _show(api, repo, name, receipt, entry, entries[-1]["entry_digest"], app_id, prs)
        # PR state is outside the writer group: re-read it with the ledger.
        now = _newest(*_verified(api, repo, ref), repo, head, _open_prs(api, repo, head))
        if {k: (v[0], v[2]) for k, v in now.items()} == {k: (v[0], v[2]) for k, v in shown.items()}:
            return {k: v[0] for k, v in shown.items()}
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"the ledger kept moving under {repo}@{head}")


def _grants(perms: Any, scope: str) -> bool:
    """Whether a parsed ``permissions`` value grants ``scope`` write. Absent
    means the repository default (read); any form but read-all, {} or a
    mapping of read/write/none fails closed (so write-all)."""
    if perms is None or perms == "read-all":
        return False
    if isinstance(perms, dict) and all(isinstance(k, str) and v in ("read", "write", "none") for k, v in perms.items()):
        return perms.get(scope) == "write"
    return True


def _token_writes(job: dict[str, Any], scope: str) -> bool:
    """Whether a step's inputs request ``scope`` write: a ``permission-<scope>``
    input other than read/none, or an App token with no ``permission-*``
    inputs, which carries every App permission (the Mandate App has checks
    and contents write). An unreadable step fails closed."""
    steps = job.get("steps") or []
    if not isinstance(steps, list):
        return True
    for step in steps:
        inputs = step.get("with") or {} if isinstance(step, dict) else None
        if not isinstance(inputs, dict):
            return True
        asked = {k: v for k, v in inputs.items() if isinstance(k, str) and k.startswith("permission-")}
        if "create-github-app-token" in str(step.get("uses", "")) and not asked:
            return True
        if asked.get(f"permission-{scope}") not in (None, "read", "none"):
            return True
    return False


def _reconciles(job: dict[str, Any]) -> bool:
    """A step runs the supported reconciler: the one command, unconditionally,
    failing the job if it fails, with ``shell: bash`` on the step and a
    GitHub-hosted Ubuntu runner (the default shell and python3 depend on the
    runner: PowerShell on Windows). A bounded contract, not shell analysis."""
    return bool(re.fullmatch(r"ubuntu-[\w.-]+", str(job.get("runs-on")))) and any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and bool(_RECONCILE.fullmatch(re.sub(r"\\\n\s*", " ", step["run"]).strip()))
        and str(step.get("if", "always()")).replace(" ", "") in _ALWAYS
        and step.get("continue-on-error", False) is False
        and step.get("shell") == "bash"
        for step in job.get("steps") or []
    )


def _workflow(text: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """The parsed workflow and, per job, its raw lines at the job's own
    indentation (comments, which parsing drops). Duplicate and merge keys
    raise: what they mean depends on the parser."""
    import yaml  # ponytail: test-time scan only; CI has PyYAML through yamllint

    class Strict(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> Any:
            # A merge key (<<) has no constructor here, so building it raises.
            keys = [repr(self.construct_object(k, deep=True)) for k, _ in node.value]
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate key")
            return super().construct_mapping(node, deep)

    doc = yaml.load(text, Loader=Strict)  # noqa: S506 (SafeLoader subclass)
    root = yaml.compose(text, Loader=Strict)
    lines = text.splitlines()
    jobs_node = next(v for k, v in root.value if k.value == "jobs")
    own = {}
    for k, v in jobs_node.value:
        column = v.start_mark.column
        own[k.value] = [x for x in lines[k.start_mark.line : v.end_mark.line] if x[:column].strip() == "" and x[column : column + 1] != " "]
    if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
        raise ValueError("no jobs")
    return doc, own


def serial_violations(workflows: dict[str, str]) -> list[str]:
    """``file:job`` for each job that breaks the writer boundary, read from the
    parsed YAML (so quoting, aliases and comments hide nothing): one that can
    write checks outside the canonical per-head job concurrency group, one
    that can record receipts (contents write, unless the job states
    ``# mandate: no-receipts`` at its own indentation and doesn't use them)
    inside any concurrency group, where GitHub can replace it while pending,
    or that no grouped publisher follows (one that needs exactly it, runs
    ``if: always()`` and has a step that runs the supported reconciler, main(),
    as _reconciles() reads it), or one that uses receipts without declaring its
    permissions. A file that doesn't parse to jobs, or has duplicate or merge
    keys, is ``file:?``. It sees only what YAML shows: a script handed a
    credential is outside it (mandate/README.md, credentials)."""
    import yaml  # noqa: F401  a missing parser is an error, never "every file unreadable"

    bad = []
    for name, text in sorted(workflows.items()):
        try:
            doc, own = _workflow(text)
            jobs = doc["jobs"]
            if not all(isinstance(job, dict) for job in jobs.values()):
                raise ValueError("unreadable job")
        except Exception:  # anything this scan can't read fails closed
            bad.append(f"{name}:?")
            continue
        header = {k: v for k, v in doc.items() if k != "jobs"}
        info = {}
        for job_name, job in jobs.items():
            blob = json.dumps([header, job], default=str)
            uses = _USES_RECEIPTS.search(blob)
            perms = [doc.get("permissions"), job.get("permissions")]
            publishes = (
                any(_grants(x, "checks") for x in perms)
                or _token_writes(job, "checks")
                or re.search(r"check-runs|check_runs|(?i:createCheckRun|updateCheckRun)", blob)
            )
            concurrency = job.get("concurrency")
            canonical = (
                isinstance(concurrency, dict)
                and concurrency.get("group") == CANONICAL_GROUP
                and concurrency.get("cancel-in-progress") is False
            )
            # A wrapper script can hide the import, so a job that can write
            # contents records unless it states it doesn't (and doesn't use them).
            stated = any(re.fullmatch(r" *# mandate: no-receipts\b.*", x) for x in own.get(job_name, []))
            records = (any(_grants(x, "contents") for x in perms) or _token_writes(job, "contents")) and not (stated and not uses)
            needs = job.get("needs") or []
            # It reconciles after exactly one job, whatever that job's result.
            after = [needs] if isinstance(needs, str) else needs
            always = str(job.get("if", "")).replace(" ", "") in _ALWAYS
            reconciles = _reconciles(job)
            info[job_name] = (publishes, canonical, records, uses, after if always and reconciles else None)
        for job_name, (publishes, canonical, records, uses, _) in info.items():
            job = jobs[job_name]
            if (
                (publishes and not canonical)
                or (records and ("concurrency" in doc or "concurrency" in job))
                # A recorder is followed by a grouped publisher that always
                # runs after it and runs the reconciler, so a newer refusal
                # never leaves an older success.
                or (records and not any(p and c and follows == [job_name] for p, c, _, _, follows in info.values()))
                or (uses and "permissions" not in doc and "permissions" not in job)
            ):
                bad.append(f"{name}:{job_name}")
    return bad


def _delegation(repository: str, policy: str) -> Delegation:
    """The owner's delegation at the commit a receipt's policy pins. A policy
    naming another delegation repository fails _authorized (its source differs)."""
    return fetch(repository, policy.partition("@")[2].partition(":")[0])


def main(
    argv: list[str] | None = None,
    api: l.Api = l.gh_api,
    delegations: Callable[[str, str], Delegation] = _delegation,
) -> int:
    """The supported publisher entrypoint; a recorder's follower must run it
    (serial_violations()): PYTHONPATH=mandate/src python3 -m mandate.receipt reconcile ..."""
    parser = argparse.ArgumentParser(description="Show a head commit's newest recorded decision on its checks")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("reconcile", help="reconcile_check(): the only check publisher")
    run.add_argument("repository")
    run.add_argument("ref", help="the ledger branch")
    run.add_argument("head", help="the head commit SHA")
    run.add_argument("--app-id", type=int, required=True, help="the publisher App; only its runs are touched")
    args = parser.parse_args(argv)
    try:
        shown = reconcile_check(api, args.repository, args.ref, args.head, app_id=args.app_id, delegations=delegations)
    except (l.LedgerError, l.ApiError, ValueError) as exc:  # the check already failed closed
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    for name, entry in shown.items():
        print(f"{name}: {entry['decision_id']}/{entry['receipt_revision']}")
    return 0


def trailers(
    api: l.Api,
    repo: str,
    ref: str,
    subject: dict[str, Any],
    fresh: dict[str, Any],
    delegation: Delegation,
    *,
    after: str | None,
) -> str:
    """Merge-commit trailers after final revalidation.

    ``subject`` is what the merge worker acted on; ``fresh`` is a receipt from
    a decision taken just now. It must still be about that subject and
    AUTHORIZE. It is then recorded as a new revision, so the trailers always
    name this decision's latest revision,
    never a superseded one a stale worker still holds. ``after`` is
    pr_latest() as read before deciding ``fresh`` (see record()).
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
    if not LIVE.fullmatch(subject["enforcement"]):
        raise l.LedgerError(
            "CONTRACT_ERROR", f"enforcement {subject['enforcement']!r} is not a live snapshot: shadow grants nothing"
        )
    if fresh["decision"]["outcome"] != "AUTHORIZE":
        raise l.LedgerError("CONTRACT_ERROR", f"fresh outcome is {fresh['decision']['outcome']}")
    entry, chain_head, _ = record(api, repo, ref, fresh, delegation, after=after)
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


if __name__ == "__main__":
    sys.exit(main())
