"""Receipts: one versioned record per decision revision, kept in the ledger.

A ``decision_id`` names the immutable subject: repository, pull request,
head, base, delegation revision and enforcement snapshot. Any drift is a new
ID. Under one ID, receipts are revisions r1, r2, ...: record() appends the
next one only when the decision's meaning (everything but the clock and the
revision) differs from the latest, so rerunning identical inputs is a no-op,
and flipping back to an earlier result is a new revision, never a reuse.

The merge commit is the anchor: trailers() names the exact receipt digest and
chain head, and only for an AUTHORIZE receipt that a fresh decision still
matches. audit() checks a ledger against those anchors offline and says
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


def record(
    api: l.Api, repo: str, ref: str, receipt: dict[str, Any]
) -> tuple[dict[str, Any], str, bool]:
    """(ledger entry for this decision's latest revision, chain head, appended)."""
    did = receipt["decision_id"]
    for _attempt in range(l.RETRIES):
        try:
            state = l.read(api, repo, ref)
            stored = l._receipts(api, repo, state)
        except l.ApiError as exc:
            raise l.LedgerError("LEDGER_UNAVAILABLE", str(exc)) from None
        failures = l.verify(state.text, stored)
        if failures:
            raise l.LedgerError("LEDGER_INVALID", "; ".join(failures))
        entries = [json.loads(x) for x in l._lines(state.text)]
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


def publish_check(
    api: l.Api,
    repo: str,
    receipt: dict[str, Any],
    entry: dict[str, Any],
    chain_head: str,
    *,
    shadow: bool,
) -> dict[str, Any]:
    """Create or update the one ``mandate/decision`` check run for this decision ID."""
    head, did = receipt["subject"]["head_sha"], receipt["decision_id"]
    outcome, revision = receipt["decision"]["outcome"], entry["receipt_revision"]
    conclusion = "neutral" if shadow else ("success" if outcome == "AUTHORIZE" else "failure")
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
    if len(summary) > SUMMARY_LIMIT:
        cut = "\n- … more reasons in the receipt"
        summary = summary[: SUMMARY_LIMIT - len(cut)] + cut
    payload = {
        "name": CHECK_NAME,
        "external_id": did,
        "status": "completed",
        "conclusion": conclusion,
        "output": {"title": f"{outcome} ({revision})", "summary": summary},
    }
    runs = api(
        "GET", f"repos/{repo}/commits/{head}/check-runs?check_name={quote(CHECK_NAME)}", None
    )["check_runs"]
    existing = next((x for x in runs if x.get("external_id") == did), None)
    if existing is None:
        return api("POST", f"repos/{repo}/check-runs", {**payload, "head_sha": head})
    # Never move the check back to a superseded revision. ponytail: the Checks
    # API has no compare-and-swap, so a GET/PATCH race can still land a stale
    # revision; consumers must take the latest revision from the ledger, as
    # trailers() does with a fresh decision, never from this check alone.
    shown_revision = re.search(rf"`{re.escape(did)}/r(\d+)`", (existing.get("output") or {}).get("summary") or "")
    if shown_revision and int(shown_revision.group(1)) > int(revision.removeprefix("r")):
        return existing
    shown = existing.get("output") or {}
    if existing.get("conclusion") == conclusion and all(
        shown.get(k) == v for k, v in payload["output"].items()
    ):  # GitHub adds text and annotation fields we never send
        return existing
    return api("PATCH", f"repos/{repo}/check-runs/{existing['id']}", payload)


def trailers(
    data: bytes, entry: dict[str, Any], chain_head: str, fresh: dict[str, Any]
) -> str:
    """Merge-commit trailers, after final revalidation against a fresh receipt."""
    stored = json.loads(data)
    if (
        l.digest(data) != entry["receipt_digest"]
        or stored.get("decision_id") != entry["decision_id"]
        or stored.get("receipt_revision") != entry["receipt_revision"]
    ):
        raise l.LedgerError("CONTRACT_ERROR", "receipt bytes are not the recorded revision")
    if stored["decision"]["outcome"] != "AUTHORIZE":
        raise l.LedgerError("CONTRACT_ERROR", f"receipt outcome is {stored['decision']['outcome']}")
    for field, code in (
        ("head_sha", "HEAD_CHANGED"),
        ("base_sha", "BASE_CHANGED"),
        ("enforcement", "ENFORCEMENT_DRIFT"),
    ):
        if fresh["subject"][field] != stored["subject"][field]:
            raise l.LedgerError(code, f"{field} {stored['subject'][field]} is now {fresh['subject'][field]}")
    if semantic(fresh) != semantic(stored):
        raise l.LedgerError("CONTRACT_ERROR", "a fresh decision differs from the recorded receipt")
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
