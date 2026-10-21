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
CHECK_NAME = "mandate/decision"  # the required check: live decisions only
SHADOW_CHECK_NAME = "mandate/shadow"  # never required; GitHub counts neutral as passing
SHADOW = "shadow"  # the enforcement snapshot of a decision that grants nothing
LIVE = re.compile(r"^sha256:[0-9a-f]{64}$")  # a real enforcement snapshot digest
# One writer per head commit (checks belong to a commit, not a PR): writers are
# workflows called with a ``head_sha`` input, so every caller computes this group.
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
    api: l.Api, repo: str, ref: str, receipt: dict[str, Any]
) -> tuple[dict[str, Any], str, bool]:
    """(ledger entry for this decision's latest revision, chain head, appended)."""
    did = receipt["decision_id"]
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
    passes = outcome == "AUTHORIZE" and bool(LIVE.match(enforcement)) and len(prs) == 1
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
    mine = [x for x in runs if (x.get("app") or {}).get("id") == app_id]
    if not mine and not (shadow and name == CHECK_NAME):  # never open a required run for shadow
        api("POST", f"repos/{repo}/check-runs", {**payload, "head_sha": head})
    for run in mine:  # a past race or an older decision ID; each must show this
        shown = run.get("output") or {}
        if run.get("conclusion") != conclusion or any(
            shown.get(k) != v for k, v in payload["output"].items()
        ):  # GitHub adds text and annotation fields we never send
            api("PATCH", f"repos/{repo}/check-runs/{run['id']}", payload)


def _newest(
    entries: list[dict[str, Any]], stored: dict[str, bytes], repo: str, head: str
) -> dict[str, tuple[dict[str, Any], dict[str, Any], list[int]]]:
    """Check name -> (entry, receipt, PRs) to show for this head.

    The required check follows the newest decision of any mode, so a shadow
    decision that supersedes a live one retires it; the shadow check follows
    the newest shadow decision. PRs: every PR with such a decision on the head.
    """
    found: dict[str, tuple[dict[str, Any], dict[str, Any], list[int]]] = {}
    for entry in entries:
        receipt = json.loads(stored[l.receipt_path(entry["decision_id"], entry["receipt_revision"])])
        s = receipt["subject"]
        if (s["repository"], s["head_sha"]) == (repo, head):
            names = [CHECK_NAME] + ([SHADOW_CHECK_NAME] if s["enforcement"] == SHADOW else [])
            for name in names:
                prs = sorted({*found.get(name, ({}, {}, []))[2], s["pull_request"]})
                found[name] = (entry, receipt, prs)
    return found


def reconcile_check(api: l.Api, repo: str, ref: str, head: str, *, app_id: int) -> dict[str, dict[str, Any]]:
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

    - one writer per head commit: every job that records receipts or writes
      checks runs in CANONICAL_GROUP without cancelling in progress
      (serial_violations() enforces it over the workflows);
    - if the ledger moved while this ran (only possible when that boundary is
      bypassed), it shows the newer decision before returning.

    Only runs created by ``app_id`` (the publisher App) are ours. The
    conclusion follows the receipt's recorded enforcement. Returns check name
    -> the ledger entry it left on display.
    """
    for _attempt in range(l.RETRIES):
        entries, stored = _verified(api, repo, ref)
        shown = _newest(entries, stored, repo, head)
        if not shown:
            raise l.LedgerError("CONTRACT_ERROR", f"no receipt recorded for {repo}@{head}")
        for name, (entry, receipt, prs) in shown.items():
            _show(api, repo, name, receipt, entry, entries[-1]["entry_digest"], app_id, prs)
        now = _newest(*_verified(api, repo, ref), repo, head)
        if {k: v[0] for k, v in now.items()} == {k: v[0] for k, v in shown.items()}:
            return {k: v[0] for k, v in shown.items()}
    raise l.LedgerError("LEDGER_UNAVAILABLE", f"the ledger kept moving under {repo}@{head}")


def _serialized(block: str, indent: str) -> bool:
    """Whether ``concurrency`` at exactly this level (workflow: "", job: four
    spaces) names the canonical group without cancelling. GitHub applies no
    other concurrency, so a nested mapping (a matrix value) never counts."""
    found = re.search(rf"(?m)^{indent}concurrency:[ \t]*\n((?:{indent} +\S.*\n?)+)", block)
    if not found:
        return False
    keys = dict(re.findall(rf"(?m)^{indent}  ([\w-]+):[ \t]*(.*?)[ \t]*$", found.group(1)))
    return (
        keys.get("group", "").strip("'\"") == CANONICAL_GROUP
        and keys.get("cancel-in-progress") == "false"
    )


def _may_write_checks(block: str) -> bool:
    """Whether a workflow header or job block can write checks, scanning every
    line (so blank lines or nesting hide nothing) and failing closed.

    A line can write checks if, outside comments, it mentions ``checks`` other
    than as ``checks: read|none``, or sets ``permissions:`` inline to anything
    but ``read-all`` or ``{}`` (so ``write-all``), or uses a YAML alias or
    merge key. An App token step without ``permission-*`` inputs also counts:
    it carries every App permission, and the Mandate App has checks: write.

    It guards against mistakes, not an adversary who can edit workflows:
    workflow changes are themselves owner decisions at the merge gate.
    """
    for raw in block.splitlines():
        if raw.lstrip().startswith("#"):
            continue  # a whole-line comment
        line = raw if ("'" in raw or '"' in raw) else re.sub(r"\s#.*", "", raw)  # a quoted # stays
        if re.search(r"\bchecks\b", line) and not re.fullmatch(r" *checks: *(read|none) *", line):
            return True
        if re.search(r"<<:|(?:^|[:\-])\s+\*[\w-]+\s*$", line):
            return True
        inline = re.fullmatch(r" *permissions:[ \t]*(.*?)[ \t]*", line)
        if inline and inline.group(1) not in ("", "read-all", "{}"):
            return True
    for step in re.split(r"(?m)^(?= *- )", block):
        if "create-github-app-token" in step and not re.search(r"(?m)^ *permission-[\w-]+:", step):
            return True
    return False


def serial_violations(workflows: dict[str, str]) -> list[str]:
    """``file:job`` for each job that records receipts or can write checks
    outside the canonical per-PR concurrency group."""
    bad = []
    for name, text in sorted(workflows.items()):
        header, _, body = text.partition("\njobs:\n")
        jobs = re.findall(r"(?m)^  ([\w-]+):[ \t]*\n((?:(?:    .*)?\n?)*)", body)
        # Every line of jobs: must be a job key or nested under one; anything
        # else (a flow-mapping job, keys after jobs:) was not read: fail closed.
        unread = any(
            not re.fullmatch(r"\s*(#.*)?|  [\w-]+:[ \t]*(#.*)?|    .*", line)
            for line in body.splitlines()
        )
        if unread or (not jobs and (_USES_RECEIPTS.search(text) or _may_write_checks(text))):
            bad.append(f"{name}:?")
        for job, block in jobs:
            writes = (
                _USES_RECEIPTS.search(header + block)
                or _may_write_checks(header)
                or _may_write_checks(block)
            )
            if writes and not (_serialized(header, "") or _serialized(block, "    ")):
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
