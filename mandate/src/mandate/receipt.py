"""Receipts: one versioned record per decision revision, kept in the ledger.

A ``decision_id`` names the immutable subject: repository, pull request,
head, base, delegation revision and enforcement snapshot. Any drift is a new
ID. Under one ID, receipts are revisions r1, r2, ...: record() appends the
next one only when the decision's meaning (everything but the clock and the
revision) differs from the latest, so rerunning identical inputs is a no-op,
and flipping back to an earlier result is a new revision, never a reuse.

reconcile_check() is the only check publisher: it shows the ledger's latest
revision, and publishers run as one serialized job per head commit. Recording
needs no group: ledger appends are compare-and-swap.

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
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from mandate import ledger as l
from mandate.decision import REGISTRY, REGISTRY_VERSION, Decision, worst
from mandate.delegation import Delegation
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
_USES_RECEIPTS = re.compile(r"mandate(\.| import )receipt|src/mandate/receipt\.py")
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


def record(
    api: l.Api, repo: str, ref: str, receipt: dict[str, Any], delegation: Delegation | None = None
) -> tuple[dict[str, Any], str, bool]:
    """(ledger entry for this decision's latest revision, chain head, appended).

    ``delegation`` is the pinned delegation the decision was taken under; an
    AUTHORIZE is recorded only if it holds under it (_authorized)."""
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
    entries: list[dict[str, Any]], stored: dict[str, bytes], repo: str, head: str, open_prs: set[int]
) -> dict[str, tuple[dict[str, Any], dict[str, Any], list[int]]]:
    """Check name -> (entry, receipt, PRs) to show for this head.

    PRs: every open PR whose current head is this commit (``open_prs``),
    decided or not, since they all share the commit's one check. Candidates:
    their decisions on this head, where it is still their latest decision. The required check follows the newest
    of their decisions in any mode, so a shadow decision that supersedes a
    live one retires it; the shadow check follows the newest shadow one.
    """
    decisions: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in entries:
        if not DECISION_ID.fullmatch(entry["decision_id"]):
            continue  # not a decision (the drill's records share the ledger)
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
        if receipt["subject"]["repository"] == repo:
            decisions.append((entry, receipt))
    latest = {receipt["subject"]["pull_request"]: receipt for _, receipt in decisions}
    prs = sorted(open_prs)
    current = {pr for pr, receipt in latest.items() if receipt["subject"]["head_sha"] == head and pr in open_prs}
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


def _open_prs(api: l.Api, repo: str, head: str) -> set[int]:
    """Open PRs whose current head is this commit. GitHub lists PRs associated
    with a commit, not only those it still heads, so filter on head.sha."""
    found: set[int] = set()
    for page in range(1, 1000):
        batch = api("GET", f"repos/{repo}/commits/{head}/pulls?per_page=100&page={page}", None)
        found |= {p["number"] for p in batch if p.get("state") == "open" and (p.get("head") or {}).get("sha") == head}
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
            raise l.LedgerError("CONTRACT_ERROR", f"no receipt recorded for {repo}@{head}")
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


def _serialized(block: str) -> bool:
    """Whether the job's own ``concurrency`` names the canonical group without
    cancelling. Workflow-level concurrency serializes runs, not the jobs or
    matrix legs of one run, so it never counts; nor does a nested mapping."""
    found = re.search(r"(?m)^    concurrency:[ \t]*\n((?:     +\S.*\n?)+)", block)
    if not found:
        return False
    keys = dict(re.findall(r"(?m)^      ([\w-]+):[ \t]*(.*?)[ \t]*$", found.group(1)))
    return (
        keys.get("group", "").strip("'\"") == CANONICAL_GROUP
        and keys.get("cancel-in-progress") == "false"
    )


def _may_write(block: str, scope: str) -> bool:
    """Whether a workflow header or job block can write ``scope`` (``checks``
    or ``contents``), scanning every line (so blank lines or nesting hide
    nothing) and failing closed.

    A line can write it if, outside comments, it mentions the scope other than
    as ``<scope>: read|none``, calls the Checks API directly (``check-runs``,
    ``createCheckRun``; checks only), has a ``permissions`` key other than a
    block key or ``permissions: read-all|{}`` (so ``write-all``, quoted or
    explicit keys), or uses a YAML alias or merge key. An App token step
    without ``permission-*`` inputs also counts: it carries every App
    permission, and the Mandate App has checks and contents write.

    It guards against mistakes, not an adversary who can edit workflows:
    workflow changes are themselves owner decisions at the merge gate.
    """
    for raw in block.splitlines():
        if raw.lstrip().startswith("#"):
            continue  # a whole-line comment
        line = raw if ("'" in raw or '"' in raw) else re.sub(r"\s#.*", "", raw)  # a quoted # stays
        if re.search(rf"\b{scope}\b", line) and not re.fullmatch(rf" *{scope}: *(read|none) *", line):
            return True
        if scope == "checks" and re.search(r"check-runs|check_runs|(?i:createCheckRun|updateCheckRun)", line):
            return True  # a direct Checks API call, whatever token it uses
        if re.search(r"<<:|(?:^|[:\-])\s+\*[\w-]+\s*$", line):
            return True
        key = re.search(r"""\bpermissions\b["']?\s*:|\?\s*["']?permissions\b""", line)
        if key and not re.fullmatch(r" *permissions:[ \t]*(read-all|\{\})?[ \t]*", line):
            return True
    for step in re.split(r"(?m)^(?= *- )", block):
        if "create-github-app-token" in step and not re.search(r"(?m)^ *permission-[\w-]+:", step):
            return True
    return False


def serial_violations(workflows: dict[str, str]) -> list[str]:
    """``file:job`` for each job that breaks the writer boundary: one that can
    write checks outside the canonical per-head job concurrency group, one
    that can record receipts (uses them with contents write) inside any
    concurrency group, where GitHub can replace it while pending, or one that
    uses receipts without declaring its permissions."""
    bad = []
    for name, text in sorted(workflows.items()):
        header, _, body = text.partition("\njobs:\n")
        jobs = re.findall(r"(?m)^  ([\w-]+):[ \t]*(?:#.*)?\n((?:(?:    .*)?\n?)*)", body)
        # Every line of jobs: must be a job key or nested under one; anything
        # else (a flow-mapping job, keys after jobs:) was not read: fail closed.
        unread = any(
            not re.fullmatch(r"\s*(#.*)?|  [\w-]+:[ \t]*(#.*)?|    .*", line)
            for line in body.splitlines()
        )
        if unread or (not jobs and (_USES_RECEIPTS.search(text) or _may_write(text, "checks"))):
            bad.append(f"{name}:?")
        for job, block in jobs:
            uses = _USES_RECEIPTS.search(header + block)
            publishes = _may_write(header, "checks") or _may_write(block, "checks")
            records = uses and (_may_write(header, "contents") or _may_write(block, "contents"))
            if (
                (publishes and not _serialized(block))
                or (records and re.search(r"\bconcurrency\b", header + block))
                or (uses and not re.search(r"(?m)^ *permissions:", header + block))
            ):
                bad.append(f"{name}:{job}")
    return bad


def trailers(
    api: l.Api, repo: str, ref: str, subject: dict[str, Any], fresh: dict[str, Any], delegation: Delegation
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
    if not LIVE.fullmatch(subject["enforcement"]):
        raise l.LedgerError(
            "CONTRACT_ERROR", f"enforcement {subject['enforcement']!r} is not a live snapshot: shadow grants nothing"
        )
    if fresh["decision"]["outcome"] != "AUTHORIZE":
        raise l.LedgerError("CONTRACT_ERROR", f"fresh outcome is {fresh['decision']['outcome']}")
    entry, chain_head, _ = record(api, repo, ref, fresh, delegation)
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
