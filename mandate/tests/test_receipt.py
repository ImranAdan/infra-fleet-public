"""Receipt checks (KAN-26). Run: python3 mandate/tests/test_receipt.py

Real decide() output becomes a versioned receipt, recorded through the real
ledger.append() against the fast-forward-only FakeGit from test_ledger. The
check-run publisher runs against a fake checks API. Nothing calls GitHub.
"""

from __future__ import annotations

import json
import functools
import re
import sys
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from test_ledger import REF, REPO, FakeGit, receipts  # noqa: E402

from mandate import decision as m  # noqa: E402
from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import ledger as l  # noqa: E402
from mandate import receipt as r  # noqa: E402

HEAD, BASE = "a" * 40, "b" * 40
POLICY = "ImranAdan/mandate-delegation@" + "d" * 40 + ":repositories/r.toml"
SUBJECT = e.Subject(REPO, HEAD, BASE, POLICY)
VERSIONS = {"package": "0.1.0", "adapter": 1}
ACTORS = {"app_id": 5336871}
APP = 5336871  # the publisher App; runs from other Apps are never touched
# The pinned delegation every receipt here was decided under (decision-prose
# authorizes with intent-gate evidence). Only enforce mode grants authority.
EXAMPLE = (HERE.parent / "examples" / "infra-fleet-public.toml").read_text().replace(
    'repository = "ImranAdan/infra-fleet-public"', f'repository = "{REPO}"'
)
DELEG = d.parse(EXAMPLE.replace('mode = "shadow"', 'mode = "enforce"'), REPO, POLICY)
SHADOW_DELEG = d.parse(EXAMPLE, REPO, POLICY)
RESOLVE = lambda repository, policy: DELEG  # noqa: E731
ENF = "sha256:" + "e" * 64  # a live enforcement snapshot


def proof(subject: e.Subject) -> e.EvidenceRecord:
    """A successful intent-gate record about exactly this subject."""
    return e.EvidenceRecord(
        version=e.VERSION, check="Intent gate / Declared intent", conclusion="success",
        app_id=e.ACTIONS_APP_ID, app_slug="github-actions", check_run_id=70, check_suite_id=700,
        run_id=7, run_attempt=1, workflow=".github/workflows/intent-gate.yml", event="pull_request",
        head_branch="x", repository=subject.repository, head_sha=subject.head_sha,
        base_sha=subject.base_sha, policy=subject.policy, started_at=None, completed_at=None,
    )


def decision(outcome: str = "AUTHORIZE", subject: e.Subject = SUBJECT) -> m.Decision:
    """What decide() returns: AUTHORIZE names its classes and accepted evidence."""
    if outcome == "AUTHORIZE":
        return m.Decision(outcome, (), ("decision-prose",), (("intent-gate", (proof(subject),)),), POLICY, subject)
    return m.Decision(outcome, (m.reason("UNCLASSIFIED", "x.py"),), (), (), POLICY, subject)


def build(dec: m.Decision, at: str = "2026-10-21T00:00:00Z", enforcement: str = "shadow") -> dict:
    return r.build(dec, 7, enforcement, versions=VERSIONS, actors=ACTORS, evaluated_at=at)


def enforced(dec: m.Decision, at: str = "2026-10-21T00:00:00Z") -> dict:
    return build(dec, at, enforcement=ENF)


def put(api, receipt: dict, delegation=None):
    """record() as a lone recorder: observe the PR's latest receipt, then record."""
    s = receipt.get("subject") if isinstance(receipt.get("subject"), dict) else {}
    after = r.pr_latest(api, REPO, REF, s.get("repository", REPO), s.get("pull_request", 7))
    return r.record(api, REPO, REF, receipt, delegation, after=after)


def refused(code: str, fn, *args) -> None:
    try:
        fn(*args)
    except l.LedgerError as exc:
        assert exc.code == code, exc
    else:
        raise AssertionError(f"expected {code}")


class FakeChecks:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.writes = 0
        self.shown: list[tuple[str, str]] = []  # every (conclusion, title) ever written
        self.before_write = None  # a concurrent publisher, run once
        self.fail_writes = 0  # provider errors on the next writes
        self.open_prs = {7}  # PRs GitHub lists as open on the commit
        self.pr_heads: dict[int, str] = {}  # a PR whose current head moved elsewhere

    def __call__(self, method: str, path: str, payload):
        if method == "GET":
            # Like GitHub: filter defaults to latest (newest run per suite; one
            # suite here), and pages are short, so callers must page by total.
            name = re.search(r"[?&]check_name=([^&]+)", path)
            runs = [
                dict(x)
                for x in self.runs
                if x["head_sha"] in path and (not name or x["name"] == unquote(name.group(1)))
            ]
            if "filter=all" not in path:
                runs = runs[-1:]
            page = int(re.search(r"[?&]page=(\d+)", path).group(1)) if "page=" in path else 1
            return {"total_count": len(runs), "check_runs": runs[page - 1 : page]}
        if self.before_write:
            racer, self.before_write = self.before_write, None
            racer()
        if self.fail_writes:
            self.fail_writes -= 1
            raise l.ApiError(502, "provider error")
        self.writes += 1
        self.shown.append((payload["conclusion"], payload["output"]["title"]))
        # GitHub echoes output with keys the payload never sends.
        output = {**payload["output"], "text": None, "annotations_count": 0}
        if method == "POST":
            self.runs.append(
                {**payload, "output": output, "id": len(self.runs) + 1, "app": {"id": APP}}
            )
            return self.runs[-1]
        run = next(x for x in self.runs if path.endswith(f"/check-runs/{x['id']}"))
        run.update({**payload, "output": output})
        return run


def both(checks: FakeChecks, git: FakeGit):
    """One provider: check-run calls go to the checks fake, PRs for a commit
    to its open set, the rest to Git."""

    def api(method, path, payload):
        if "/pulls" in path:  # PRs associated with the commit, paged like GitHub
            commit = re.search(r"/commits/([0-9a-f]+)/pulls", path).group(1)
            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            listed = [
                {"number": n, "state": "open", "head": {"sha": checks.pr_heads.get(n, commit)}}
                for n in sorted(checks.open_prs)
            ]
            return listed[(page - 1) * 100 : page * 100]
        return (checks if "check-runs" in path else git)(method, path, payload)

    return api


def visible(checks: FakeChecks) -> list[tuple[str, str]]:
    return [(x["conclusion"], x["output"]["title"]) for x in checks.runs]


def main() -> int:
    # Golden vector: the decision ID is fixed by the subject alone.
    receipt = build(decision())
    assert receipt["decision_id"] == r.decision_id(REPO, 7, HEAD, BASE, POLICY, "shadow")
    assert (
        receipt["decision_id"]
        == "d-8c29ce03a4349b4e07b8889284082d389f3076631fe1520d7949cd1d918bb98f"
    ), receipt["decision_id"]
    assert receipt["schema_version"] == r.SCHEMA_VERSION == 1
    assert receipt["subject_digest"] == "sha256:" + receipt["decision_id"][2:]

    # Drift in any subject field, including enforcement, is a new decision ID.
    ids = {
        r.decision_id(REPO, 7, HEAD, BASE, POLICY, "shadow"),
        r.decision_id(REPO, 8, HEAD, BASE, POLICY, "shadow"),
        r.decision_id(REPO, 7, "c" * 40, BASE, POLICY, "shadow"),
        r.decision_id(REPO, 7, HEAD, "c" * 40, POLICY, "shadow"),
        r.decision_id(REPO, 7, HEAD, BASE, POLICY + "x", "shadow"),
        r.decision_id(REPO, 7, HEAD, BASE, POLICY, "sha256:e"),
    }
    assert len(ids) == 6

    # First record appends r1; a rerun of the same inputs (later clock) is a no-op.
    git = FakeGit()
    first, head1, appended = put(git, receipt, DELEG)
    assert appended and first["receipt_revision"] == "r1" and first["seq"] == 0
    assert head1 == first["entry_digest"]
    tip = git.refs[REF]
    again, head2, appended = put(git, build(decision(), at="2026-10-21T09:00:00Z"), DELEG)
    assert not appended and again == first and head2 == head1 and git.refs[REF] == tip

    # A changed outcome under the same subject is the next revision, same ID;
    # flipping back is a third revision, never a reuse of r1.
    second, _, appended = put(git, build(decision("ESCALATE")), DELEG)
    assert appended and second["receipt_revision"] == "r2"
    assert second["decision_id"] == first["decision_id"]
    third, _, appended = put(git, build(decision()), DELEG)
    assert appended and third["receipt_revision"] == "r3"

    # Receipts are canonical, versioned and name their own revision.
    stored = json.loads(receipts(git)[l.receipt_path(first["decision_id"], "r2")])
    assert stored["receipt_revision"] == "r2" and stored["decision"]["outcome"] == "ESCALATE"
    assert l.verify(git.files(REF)[l.LEDGER].decode(), receipts(git)) == []

    # Another PR's concurrent append: re-read and append after it.
    race = FakeGit()
    other = r.build(decision(), 8, "shadow", versions=VERSIONS, actors=ACTORS, evaluated_at="t")
    race.before_advance = lambda: put(race, other, DELEG)
    mine, _, appended = put(race, receipt, DELEG)
    assert appended and mine["seq"] == 1, mine

    # Codex bot: recorders run outside the group, so they can finish out of
    # order. A newer receipt for the same PR lands after this decision saw the
    # ledger: this one is stale, never appended over it. Same decision ID or
    # another (the head or base moved), the newer ESCALATE stays the latest.
    for later in (enforced(decision("ESCALATE")), enforced(decision("ESCALATE", subject=e.Subject(REPO, HEAD, "c" * 40, POLICY)))):
        same, checks = FakeGit(), FakeChecks()
        checks.open_prs = {7}
        same.before_advance = lambda later=later: put(same, later, DELEG)
        # This decision saw no receipt (after=None); the ESCALATE lands mid-append.
        refused("STALE_DECISION", lambda: r.record(same, REPO, REF, enforced(decision()), DELEG, after=None))
        index = [json.loads(x) for x in same.files(REF)[l.LEDGER].decode().splitlines()]
        assert [x["outcome"] for x in index] == ["ESCALATE"], index
        r.reconcile_check(both(checks, same), REPO, REF, later["subject"]["head_sha"], app_id=APP, delegations=RESOLVE)
        assert visible(checks) == [("failure", "ESCALATE (r1)")], visible(checks)
    # Deciding again after observing the newer receipt records normally.
    assert put(same, enforced(decision()), DELEG)[2]
    # Another repository's PR with the same number is another PR.
    foreign_pr = FakeGit()
    foreign_pr.before_advance = lambda: put(foreign_pr, enforced(decision("ESCALATE", subject=e.Subject("x/y", HEAD, BASE, POLICY))))
    assert r.record(foreign_pr, REPO, REF, enforced(decision()), DELEG, after=None)[2]
    # A concurrent decision that means the same (only its clock differs) is a
    # no-op, not stale: it changes nothing.
    ident = FakeGit()
    ident.before_advance = lambda: put(ident, enforced(decision()), DELEG)
    assert r.record(ident, REPO, REF, enforced(decision(), at="2026-10-21T00:00:01Z"), DELEG, after=None)[2] is False

    # A tampered receipt is never trusted for the no-op comparison, even when
    # it still says the same thing (re-serialized, so its digest differs).
    for tampered in (b'{"x":1}', json.dumps({**receipt, "receipt_revision": "r1"}, indent=1).encode()):
        bad = FakeGit()
        put(bad, receipt, DELEG)
        path = l.receipt_path(receipt["decision_id"], "r1")
        bad.objects[bad.objects[bad.refs[REF]]["tree"]]["files"][path] = tampered
        refused("LEDGER_INVALID", put, bad, receipt, DELEG)

    # Check run: the reconciler shows the newest decision recorded for a PR
    # head; the caller names the head, never a decision or revision. A shadow
    # receipt is published only under mandate/shadow, never the required name
    # (GitHub counts neutral as passing a required check).
    did = receipt["decision_id"]
    checks = FakeChecks()
    api = both(checks, git)
    r.reconcile_check(api, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    r.reconcile_check(api, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert checks.writes == 1 and len(checks.runs) == 1
    run = checks.runs[0]
    assert run["name"] == r.SHADOW_CHECK_NAME == "mandate/shadow" != r.CHECK_NAME == "mandate/decision"
    assert run["external_id"] == did and visible(checks) == [("neutral", "AUTHORIZE (r3)")]
    assert third["receipt_digest"] in run["output"]["summary"]

    # A live receipt passes or fails on its outcome.
    live = FakeGit()
    did = put(live, enforced(decision()), DELEG)[0]["decision_id"]
    ck0 = FakeChecks()
    r.reconcile_check(both(ck0, live), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck0) == [("success", "AUTHORIZE (r1)")], visible(ck0)
    assert ck0.runs[0]["name"] == r.CHECK_NAME
    # Only a live sha256 snapshot can pass, matched whole (a trailing newline
    # is not live); any other enforcement fails closed.
    nl = FakeGit()
    put(nl, build(decision(), enforcement=ENF + "\n"), DELEG)
    ck_nl = FakeChecks()
    r.reconcile_check(both(ck_nl, nl), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck_nl) == [("failure", "AUTHORIZE (r1)")], visible(ck_nl)
    odd = FakeGit()
    odd_id = put(odd, build(decision(), enforcement="live"), DELEG)[0]["decision_id"]
    ck_odd = FakeChecks()
    r.reconcile_check(both(ck_odd, odd), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck_odd) == [("failure", "AUTHORIZE (r1)")], visible(ck_odd)

    # A run from another App with the same name and external_id is not ours:
    # we publish our own and never touch it.
    ck0.runs.insert(0, {**ck0.runs[0], "id": 99, "app": {"id": 999}, "conclusion": "failure"})
    ck0.runs.pop(1)
    r.reconcile_check(both(ck0, live), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert [(x["app"]["id"], x["conclusion"]) for x in ck0.runs] == [(999, "failure"), (APP, "success")]

    # Codex F1 interleaving: a delayed publisher read r2 AUTHORIZE; before its
    # write lands, r3 ESCALATE is recorded and shown. The delayed write happens
    # (stale success), then it re-reads the ledger and restores r3.
    lg, ck = FakeGit(), FakeChecks()
    api2 = both(ck, lg)
    put(lg, enforced(decision("ESCALATE")), DELEG)
    r.reconcile_check(api2, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    put(lg, enforced(decision()), DELEG)

    def newer() -> None:
        put(lg, enforced(decision("ESCALATE"), at="2026-10-21T01:00:00Z"), DELEG)
        r.reconcile_check(api2, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)

    ck.before_write = newer
    r.reconcile_check(api2, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert ("success", "AUTHORIZE (r2)") in ck.shown, ck.shown  # the race really ran
    assert visible(ck) == [("failure", "ESCALATE (r3)")], visible(ck)

    # The same race on first publication creates two runs; both end at the latest.
    lg2, ck2 = FakeGit(), FakeChecks()
    api3 = both(ck2, lg2)
    put(lg2, enforced(decision()), DELEG)
    ck2.before_write = lambda: (
        put(lg2, enforced(decision("ESCALATE")), DELEG),
        r.reconcile_check(api3, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE),
    )
    r.reconcile_check(api3, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck2) == [("failure", "ESCALATE (r2)")] * 2, visible(ck2)
    # A later revision reaches both duplicates, not just the newest one.
    put(lg2, enforced(decision()), DELEG)
    r.reconcile_check(api3, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck2) == [("success", "AUTHORIZE (r3)")] * 2, visible(ck2)

    # A new decision ID on the same head (here the base moved) supersedes the
    # old one on the same check: a late reconcile shows the newest decision.
    moved_base = FakeGit()
    ck_m = FakeChecks()
    api_m = both(ck_m, moved_base)
    put(moved_base, enforced(decision()), DELEG)
    r.reconcile_check(api_m, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    new_base = enforced(decision("ESCALATE", subject=e.Subject(REPO, HEAD, "c" * 40, POLICY)))
    put(moved_base, new_base, DELEG)
    r.reconcile_check(api_m, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck_m) == [("failure", "ESCALATE (r1)")], visible(ck_m)
    assert ck_m.runs[0]["external_id"] == new_base["decision_id"]
    # ... and the same while a delayed reconcile still holds the old decision.
    race_m, ck_rm = FakeGit(), FakeChecks()
    api_rm = both(ck_rm, race_m)
    put(race_m, enforced(decision("ESCALATE")), DELEG)
    r.reconcile_check(api_rm, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    put(race_m, enforced(decision()), DELEG)
    ck_rm.before_write = lambda: (
        put(race_m, new_base, DELEG),
        r.reconcile_check(api_rm, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE),
    )
    r.reconcile_check(api_rm, REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert ("success", "AUTHORIZE (r2)") in ck_rm.shown, ck_rm.shown
    assert visible(ck_rm) == [("failure", "ESCALATE (r1)")], visible(ck_rm)

    # Checks belong to a commit: every PR GitHub lists as open with this commit
    # as its current head shares the one check, decided or not. More than one
    # cannot be represented by one check, so it fails closed.
    shared, ck_s = FakeGit(), FakeChecks()
    put(shared, enforced(decision()), DELEG)  # only #7 is decided

    def reconcile_shared() -> None:
        r.reconcile_check(both(ck_s, shared), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)

    # Codex R2-F1: #8 is open on the same head with no receipt: never green.
    ck_s.open_prs = {7, 8}
    reconcile_shared()
    assert visible(ck_s) == [("failure", "AUTHORIZE (r1), head shared by 2 PRs")], visible(ck_s)
    assert "#7, #8" in ck_s.runs[0]["output"]["summary"]
    # #8 closes: #7 alone again.
    ck_s.open_prs = {7}
    reconcile_shared()
    assert visible(ck_s) == [("success", "AUTHORIZE (r1)")], visible(ck_s)
    # #8 is listed for the commit but its current head moved (no newer receipt): not sharing.
    ck_s.open_prs, ck_s.pr_heads = {7, 8}, {8: "f" * 40}
    reconcile_shared()
    assert visible(ck_s) == [("success", "AUTHORIZE (r1)")], visible(ck_s)
    ck_s.pr_heads = {}
    # Both decided and open: still fails closed.
    put(shared, r.build(decision(), 8, ENF, versions=VERSIONS, actors=ACTORS, evaluated_at="t"), DELEG)
    reconcile_shared()
    assert visible(ck_s) == [("failure", "AUTHORIZE (r1), head shared by 2 PRs")], visible(ck_s)
    # Many PRs: the title stays within GitHub's 255 characters.
    ck_s.open_prs = set(range(7, 120))
    reconcile_shared()
    assert len(ck_s.runs[0]["output"]["title"]) <= 255 and "113 PRs" in ck_s.runs[0]["output"]["title"]
    # A PR reopened while a reconcile runs is seen before it returns.
    # (#7 reopens: its receipt is older than #8's, so only the PR set changes.)
    ck_s.open_prs = {8}
    ck_s.before_write = lambda: ck_s.open_prs.add(7)
    reconcile_shared()
    assert visible(ck_s) == [("failure", "AUTHORIZE (r1), head shared by 2 PRs")], visible(ck_s)
    # The only open PR has no decision: nothing is current, so fail closed.
    ck_s.open_prs = {9}
    refused("CONTRACT_ERROR", reconcile_shared)
    assert all(c == "failure" for c, _ in visible(ck_s)), visible(ck_s)
    # A PR whose latest decision is about another commit is not current here.
    ck_s.open_prs = {7}
    put(shared, enforced(decision(subject=e.Subject(REPO, "f" * 40, BASE, POLICY))), DELEG)
    refused("CONTRACT_ERROR", reconcile_shared)

    # A shadow decision that supersedes a live AUTHORIZE retires the required
    # check: shadow grants nothing, so mandate/decision must not stay green.
    to_shadow, ck_ts = FakeGit(), FakeChecks()
    put(to_shadow, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_ts, to_shadow), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    put(to_shadow, build(decision()), DELEG)
    r.reconcile_check(both(ck_ts, to_shadow), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    by_name = {x["name"]: x["conclusion"] for x in ck_ts.runs}
    assert by_name == {r.CHECK_NAME: "failure", r.SHADOW_CHECK_NAME: "neutral"}, by_name
    # A head that only ever had shadow decisions gets no required-name run.
    assert {x["name"] for x in checks.runs} == {r.SHADOW_CHECK_NAME}

    # Other receipt schemas in the ledger (the drill's) are not decisions:
    # skipped, never a crash that leaves an old check standing. A receipt that
    # claims this schema but is malformed is refused as an invalid ledger.
    drilled, ck_d = FakeGit(), FakeChecks()
    l.append(drilled, REPO, REF, "drill-1", "r1", l.canonical({"drill": "1", "outcome": "AUTHORIZE"}),
             l.digest(b"subject"), "AUTHORIZE", "t")
    put(drilled, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_d, drilled), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck_d) == [("success", "AUTHORIZE (r1)")], visible(ck_d)
    # A newer receipt for this head that claims the schema but lacks a field
    # _show() reads (here: reasons) is refused, and the required check that
    # was green fails closed rather than staying green.
    bad = {**enforced(decision("ESCALATE"), at="later"), "receipt_revision": "r2"}
    del bad["decision"]["reasons"]
    l.append(drilled, REPO, REF, bad["decision_id"], "r2", l.canonical(bad), bad["subject_digest"], "ESCALATE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_d, drilled), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert [(x["conclusion"], x["output"]["title"]) for x in ck_d.runs] == [("failure", "LEDGER_INVALID")], ck_d.runs
    # The same for a receipt without an outcome, and for one that is not JSON.
    for raw in ("no-outcome", "not-json"):
        gone, ck_g = FakeGit(), FakeChecks()
        put(gone, enforced(decision()), DELEG)
        r.reconcile_check(both(ck_g, gone), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
        if raw == "no-outcome":  # written below record(), which needs the outcome
            odd_receipt = {**enforced(decision("ESCALATE"), at="later"), "receipt_revision": "r2"}
            del odd_receipt["decision"]["outcome"]
            l.append(gone, REPO, REF, odd_receipt["decision_id"], "r2", l.canonical(odd_receipt),
                     odd_receipt["subject_digest"], "ESCALATE", "t")
        else:
            l.append(gone, REPO, REF, "d-" + "a" * 64, "r1", b"not json", l.digest(b"s"), "BLOCK", "t")
        refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_g, gone), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
        assert visible(ck_g) == [("failure", "LEDGER_INVALID")], (raw, visible(ck_g))
    # A provider error while showing a newer ESCALATE still fails the green run.
    flaky, ck_fl = FakeGit(), FakeChecks()
    put(flaky, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_fl, flaky), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    put(flaky, enforced(decision("ESCALATE")), DELEG)
    ck_fl.fail_writes = 1
    try:
        r.reconcile_check(both(ck_fl, flaky), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    except l.ApiError:
        pass
    else:
        raise AssertionError("a provider error was swallowed")
    assert visible(ck_fl) == [("failure", "ApiError")], visible(ck_fl)
    # An outcome the reasons contradict (AUTHORIZE beside an ESCALATE reason)
    # is refused by record() and, written below it, fails closed on reconcile.
    lying = enforced(decision("ESCALATE"))
    lying["decision"]["outcome"] = "AUTHORIZE"
    refused("CONTRACT_ERROR", put, FakeGit(), lying, DELEG)
    unregistered = enforced(decision("ESCALATE"))
    unregistered["decision"]["reasons"][0]["code"] = "MADE_UP"
    refused("CONTRACT_ERROR", put, FakeGit(), unregistered, DELEG)
    liar, ck_li = FakeGit(), FakeChecks()
    put(liar, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_li, liar), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    lie = {**lying, "evaluated_at": "later", "receipt_revision": "r2"}
    l.append(liar, REPO, REF, lie["decision_id"], "r2", l.canonical(lie), lie["subject_digest"], "AUTHORIZE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_li, liar), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_li) == [("failure", "LEDGER_INVALID")], visible(ck_li)
    # A receipt whose outer subject was changed (its ID, digest and decision
    # still name the decided head) cannot move an authorization to another head.
    moved_receipt = enforced(decision())
    moved_receipt["subject"] = {**moved_receipt["subject"], "head_sha": "f" * 40}
    refused("CONTRACT_ERROR", put, FakeGit(), moved_receipt, DELEG)
    # ... even with its ID and digest recomputed for the new head (the
    # decision inside is still about the old one) ...
    regrafted = {**moved_receipt, "subject_digest": l.digest(l.canonical(moved_receipt["subject"]))}
    regrafted["decision_id"] = "d-" + regrafted["subject_digest"].removeprefix("sha256:")
    refused("CONTRACT_ERROR", put, FakeGit(), regrafted, DELEG)
    # ... and an ID that is not its subject's is refused on its own.
    renamed = {**enforced(decision()), "decision_id": "d-" + "0" * 64}
    refused("CONTRACT_ERROR", put, FakeGit(), renamed, DELEG)
    forged = {**enforced(decision()), "subject_digest": "sha256:" + "1" * 64, "decision_id": "d-" + "1" * 64}
    refused("CONTRACT_ERROR", put, FakeGit(), forged, DELEG)
    graft, ck_gr = FakeGit(), FakeChecks()
    put(graft, enforced(decision("ESCALATE")), DELEG)
    r.reconcile_check(both(ck_gr, graft), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    planted = {**enforced(decision(subject=e.Subject(REPO, "f" * 40, BASE, POLICY))), "receipt_revision": "r1"}
    planted["subject"] = {**planted["subject"], "head_sha": HEAD}
    l.append(graft, REPO, REF, planted["decision_id"], "r1", l.canonical(planted), planted["subject_digest"], "AUTHORIZE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_gr, graft), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_gr) == [("failure", "LEDGER_INVALID")], visible(ck_gr)
    # An AUTHORIZE decide() could not have produced: reasons deleted (no class,
    # no evidence), or evidence about another head. And an unsupported
    # decision schema is refused, never skipped in favour of an older receipt.
    fabricated = enforced(decision("ESCALATE"))
    fabricated["decision"] = {**fabricated["decision"], "outcome": "AUTHORIZE", "reasons": []}
    refused("CONTRACT_ERROR", put, FakeGit(), fabricated, DELEG)
    elsewhere = enforced(decision())
    elsewhere["decision"]["accepted"][0]["records"][0]["head_sha"] = "f" * 40
    refused("CONTRACT_ERROR", put, FakeGit(), elsewhere, DELEG)
    refused("CONTRACT_ERROR", put, FakeGit(), {**enforced(decision("ESCALATE")), "schema_version": 2}, DELEG)
    future, ck_fu = FakeGit(), FakeChecks()
    put(future, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_fu, future), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    v2 = {**enforced(decision("ESCALATE"), at="later"), "schema_version": 2, "receipt_revision": "r2"}
    l.append(future, REPO, REF, v2["decision_id"], "r2", l.canonical(v2), v2["subject_digest"], "ESCALATE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_fu, future), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_fu) == [("failure", "LEDGER_INVALID")], visible(ck_fu)
    # Codex F1 (10176): an AUTHORIZE whose class, requirement and evidence the
    # pinned delegation never declared (App 0, no workflow) is refused, and no
    # successful required check can come of it.
    invented = enforced(decision("ESCALATE"))
    invented["decision"] = {
        **invented["decision"], "outcome": "AUTHORIZE", "reasons": [], "classes": ["invented-class"],
        "accepted": [{"requirement": "invented-evidence", "records": [{
            **proof(SUBJECT).to_dict(), "app_id": 0, "app_slug": None, "workflow": None,
            "run_id": None, "repository": None, "base_sha": None}]}],
    }
    refused("CONTRACT_ERROR", put, FakeGit(), invented, DELEG)
    # ... each element alone: an undeclared class, a requirement the class
    # does not name, and evidence its producer would not accept.
    for field, value in (
        ("classes", ["invented-class"]),
        ("accepted", [{"requirement": "invented-evidence", "records": [proof(SUBJECT).to_dict()]}]),
        ("accepted", [{"requirement": "intent-gate", "records": [{**proof(SUBJECT).to_dict(), "app_id": 0}]}]),
    ):
        tampered = enforced(decision())
        tampered["decision"] = {**tampered["decision"], field: value}
        refused("CONTRACT_ERROR", put, FakeGit(), tampered, DELEG)
    # ... and written below record(), it fails closed instead of going green.
    planted_ok, ck_pl = FakeGit(), FakeChecks()
    inv = {**invented, "receipt_revision": "r1"}
    l.append(planted_ok, REPO, REF, inv["decision_id"], "r1", l.canonical(inv), inv["subject_digest"], "AUTHORIZE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_pl, planted_ok), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert all(c != "success" for c, _ in visible(ck_pl)), visible(ck_pl)
    # A receipt decided under another delegation than the one given is refused.
    other = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text().replace(
        'repository = "ImranAdan/infra-fleet-public"', f'repository = "{REPO}"'), REPO, POLICY + "x")
    refused("CONTRACT_ERROR", put, FakeGit(), enforced(decision()), other)
    refused("CONTRACT_ERROR", put, FakeGit(), enforced(decision("ESCALATE")), other)
    # A shadow-mode delegation grants no merge authority: a live AUTHORIZE
    # under it is refused, while a shadow AUTHORIZE under it still records.
    refused("CONTRACT_ERROR", put, FakeGit(), enforced(decision()), SHADOW_DELEG)
    assert put(FakeGit(), build(decision()), SHADOW_DELEG)[2]
    shadow_mode, ck_sm = FakeGit(), FakeChecks()
    put(shadow_mode, enforced(decision()), DELEG)
    refused("LEDGER_INVALID", lambda: r.reconcile_check(
        both(ck_sm, shadow_mode), REPO, REF, HEAD, app_id=APP, delegations=lambda repository, policy: SHADOW_DELEG))
    # A decision on an unusable delegation records as the shadow adapter builds
    # it (no policy on subject or decision).
    unusable = m.decide(m.DecisionInput(d.DelegationError("DELEGATION_INVALID", "bad"), e.Subject(REPO, HEAD, BASE, ""), (), {}, (), ()))
    assert put(FakeGit(), build(unusable))[2]
    # Reconcile checks the AUTHORIZE against the delegation its policy names: a
    # resolver that hands back another delegation cannot make it pass.
    wrong, ck_w = FakeGit(), FakeChecks()
    put(wrong, enforced(decision()), DELEG)
    refused("LEDGER_INVALID", lambda: r.reconcile_check(
        both(ck_w, wrong), REPO, REF, HEAD, app_id=APP, delegations=lambda repository, policy: other))
    assert ck_w.runs == [], ck_w.runs

    # Codex F2 (10176): schema v1 is exact. Missing versions, actors,
    # registry_version, classes or accepted, an unknown field, or an
    # unsupported registry version are each refused.
    for strip in (("versions",), ("actors",), ("decision", "registry_version"), ("decision", "classes"),
                  ("decision", "accepted")):
        partial = enforced(decision("ESCALATE"))
        (partial if len(strip) == 1 else partial[strip[0]]).pop(strip[-1])
        refused("CONTRACT_ERROR", put, FakeGit(), partial, DELEG)
    refused("CONTRACT_ERROR", put, FakeGit(), {**enforced(decision("ESCALATE")), "extra": 1}, DELEG)
    old_registry = enforced(decision("ESCALATE"))
    old_registry["decision"]["registry_version"] = 1
    refused("CONTRACT_ERROR", put, FakeGit(), old_registry, DELEG)

    # Each receipt is bound to its index entry: an old AUTHORIZE re-appended
    # under an entry that names another revision and ESCALATE cannot win.
    rebound, ck_rb = FakeGit(), FakeChecks()
    first_ok, _, _ = put(rebound, enforced(decision()), DELEG)
    put(rebound, enforced(decision("ESCALATE")), DELEG)
    r.reconcile_check(both(ck_rb, rebound), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    old_bytes = receipts(rebound)[l.receipt_path(first_ok["decision_id"], "r1")]
    l.append(rebound, REPO, REF, first_ok["decision_id"], "r3", old_bytes, first_ok["subject_digest"], "ESCALATE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_rb, rebound), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_rb) == [("failure", "LEDGER_INVALID")], visible(ck_rb)
    # Codex R2-F2: declared types are exact. Each mutation of an otherwise
    # valid AUTHORIZE is refused by record() ...
    def first_record(x: dict) -> dict:
        return x["decision"]["accepted"][0]["records"][0]

    for label, mutate in (
        ("boolean schema_version", lambda x: x.update(schema_version=True)),
        ("float schema_version", lambda x: x.update(schema_version=1.0)),
        ("boolean registry_version", lambda x: x["decision"].update(registry_version=True)),
        ("float registry_version", lambda x: x["decision"].update(registry_version=float(m.REGISTRY_VERSION))),
        ("null check_run_id", lambda x: first_record(x).update(check_run_id=None)),
        ("string run_id", lambda x: first_record(x).update(run_id="not-a-run-id")),
        ("boolean app_id", lambda x: first_record(x).update(app_id=True)),
        ("string pull_request", lambda x: x["subject"].update(pull_request="7")),
    ):
        typed = enforced(decision())
        mutate(typed)
        try:
            put(FakeGit(), typed, DELEG)
        except l.LedgerError as exc:
            assert exc.code == "CONTRACT_ERROR", (label, exc)
        else:
            raise AssertionError(f"recorded a receipt with {label}")
    # ... and planted below record() after a green run, it retires that run.
    typed_git, ck_ty = FakeGit(), FakeChecks()
    put(typed_git, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_ty, typed_git), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    nulled = {**enforced(decision(), at="later"), "receipt_revision": "r2"}
    first_record(nulled)["check_run_id"] = None
    l.append(typed_git, REPO, REF, nulled["decision_id"], "r2", l.canonical(nulled), nulled["subject_digest"], "AUTHORIZE", "t")
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_ty, typed_git), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_ty) == [("failure", "LEDGER_INVALID")], visible(ck_ty)

    # A ledger reset to empty leaves nothing authorizing this head: fail closed.
    reset, ck_re = FakeGit(), FakeChecks()
    put(reset, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_re, reset), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    reset.objects[reset.objects[reset.refs[REF]]["tree"]]["files"][l.LEDGER] = b""
    refused("CONTRACT_ERROR", lambda: r.reconcile_check(both(ck_re, reset), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_re) == [("failure", "CONTRACT_ERROR")], visible(ck_re)
    # The same when the ledger itself cannot be verified.
    broken, ck_b = FakeGit(), FakeChecks()
    put(broken, enforced(decision()), DELEG)
    r.reconcile_check(both(ck_b, broken), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    broken.objects[broken.objects[broken.refs[REF]]["tree"]]["files"][l.LEDGER] = b'{"seq":5}\n'
    refused("LEDGER_INVALID", lambda: r.reconcile_check(both(ck_b, broken), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE))
    assert visible(ck_b) == [("failure", "LEDGER_INVALID")], visible(ck_b)

    # A receipt about another repository's commit is never shown here.
    foreign, ck_f = FakeGit(), FakeChecks()
    put(foreign, enforced(decision()), DELEG)
    put(foreign, enforced(decision("ESCALATE", subject=e.Subject("x/y", HEAD, BASE, POLICY))), DELEG)
    r.reconcile_check(both(ck_f, foreign), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
    assert visible(ck_f) == [("success", "AUTHORIZE (r1)")], visible(ck_f)

    # Single writer per head commit: every job that records receipts or can
    # write checks runs in the one canonical per-head group, without cancelling.
    group = r.CANONICAL_GROUP
    assert group == "mandate-decision-${{ github.repository }}-${{ inputs.head_sha }}"

    def wf(head: str = "", **jobs: str) -> str:
        return "on: workflow_call\n" + head + "jobs:\n" + "".join(
            f"  {name}:\n    runs-on: ubuntu-latest\n{body}" for name, body in jobs.items()
        )

    serial = f"    concurrency:\n      group: {group}\n      cancel-in-progress: false\n"
    write = "    steps:\n      - run: python3 -m mandate.receipt reconcile\n"
    top = f"concurrency:\n  group: '{group}'\n  cancel-in-progress: false\n"
    pub = "    permissions:\n      checks: write\n"
    rec = "    permissions:\n      contents: write\n"
    record = write.replace("reconcile", "record")
    token = (
        "    steps:\n      - uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1\n"
        "        with:\n          client-id: x\n"
    )
    cases = {
        "job.yml": (wf(writer=pub + serial + write), []),
        # Workflow-level concurrency serializes runs, not the jobs (or matrix
        # legs) of one run, so only job-level concurrency counts (Codex bot).
        "top.yml": (wf(top, writer=pub + write), ["top.yml:writer"]),
        "two-writers.yml": (wf(top, a=pub + write, b=pub + write), ["two-writers.yml:a", "two-writers.yml:b"]),
        "top-and-job.yml": (wf(top, writer=pub + serial + write), []),
        # A pending job in a group is replaced by a newer one, so a job that
        # can record (contents: write) must not wait in any group; appends are
        # compare-and-swap safe without one. Record, then publish (Codex bot).
        "recorder.yml": (wf(a=rec + record), []),
        "split.yml": (wf(record=rec + record, publish="    needs: record\n" + pub + serial + write), []),
        "grouped-recorder.yml": (wf(a=rec + serial + record), ["grouped-recorder.yml:a"]),
        "top-recorder.yml": (wf(top, a=rec + record), ["top-recorder.yml:a"]),
        "header-recorder.yml": (wf("permissions:\n  contents: write\n", a=serial + record), ["header-recorder.yml:a"]),
        "quoted-group-recorder.yml": (wf(a=rec + '    "concurrency": x\n' + record), ["quoted-group-recorder.yml:a"]),
        "both.yml": (
            wf(a="    permissions:\n      contents: write\n      checks: write\n" + serial + record),
            ["both.yml:a"],
        ),
        "direct-publisher.yml": (wf(a=pub + serial + write + "      - run: gh api repos/o/r/check-runs\n"), []),
        "token-recorder.yml": (wf(a=serial + token + "          permission-contents: write\n" + record), ["token-recorder.yml:a"]),
        # A receipt user must declare permissions rather than trust the default.
        "undeclared.yml": (wf(a=serial + write), ["undeclared.yml:a"]),
        # Quoted or explicit permission keys are read as anything (Codex bot).
        "quoted-key.yml": (wf(a='    "permissions": write-all\n'), ["quoted-key.yml:a"]),
        "explicit-key.yml": (wf(a="    ? permissions\n    : write-all\n"), ["explicit-key.yml:a"]),
        "bare.yml": (wf(writer=write), ["bare.yml:writer"]),
        "other-job.yml": (wf(reader=serial, writer=write), ["other-job.yml:writer"]),
        "suffix.yml": (wf(writer=pub + serial.replace("inputs.head_sha", "inputs.pr") + write), ["suffix.yml:writer"]),
        "cancel.yml": (wf(writer=pub + serial.replace("false", "true") + write), ["cancel.yml:writer"]),
        "checks.yml": (wf("permissions:\n  checks: write\n", a="    steps: []\n"), ["checks.yml:a"]),
        "job-checks.yml": (wf(a="    permissions:\n      checks: write\n"), ["job-checks.yml:a"]),
        "inline.yml": (wf(a="    steps:\n      - run: python3 -c 'from mandate import receipt'\n"), ["inline.yml:a"]),
        "app.yml": (wf(a="    steps:\n      - with:\n          permission-checks: write\n"), ["app.yml:a"]),
        "path.yml": (wf(a="    steps:\n      - run: python3 mandate/src/mandate/receipt.py\n"), ["path.yml:a"]),
        "read.yml": (wf("permissions:\n  checks: read\n", a="    steps: []\n"), []),
        "write-all.yml": (wf("permissions: write-all\n", a="    steps: []\n"), ["write-all.yml:a"]),
        # Only canonical permissions are read; any other YAML form fails closed.
        "flow.yml": (wf("permissions: {checks: write}\n", a="    steps: []\n"), ["flow.yml:a"]),
        "quoted.yml": (wf(a="    permissions:\n      checks: 'write'\n"), ["quoted.yml:a"]),
        "alias.yml": (wf(a="    permissions: *perms\n"), ["alias.yml:a"]),
        "empty.yml": (wf("permissions: {}\n", a="    steps: []\n"), []),
        "read-all.yml": (wf("permissions: read-all\n", a="    steps: []\n"), []),
        "block.yml": (wf(a="    permissions:\n      contents: read  # just reads\n      checks: none\n"), []),
        "blank.yml": (wf(a="    permissions:\n\n      checks: write\n"), ["blank.yml:a"]),
        "comment.yml": (wf(a="    # this job never writes checks: write\n    steps: []\n"), []),
        "merge-key.yml": (wf(a="    permissions:\n      <<: *perms\n"), ["merge-key.yml:a"]),
        "quoted-hash.yml": (wf(a="    permissions: {name: 'x #', checks: write}\n"), ["quoted-hash.yml:a"]),
        "direct-api.yml": (wf(a="    steps:\n      - run: gh api -X POST repos/o/r/check-runs -f name=x\n"), ["direct-api.yml:a"]),
        "graphql.yml": (wf(a="    steps:\n      - run: gh api graphql -f query='mutation { createCheckRun(input: {}) { clientMutationId } }'\n"), ["graphql.yml:a"]),
        "quoted-input.yml": (
            wf(a="    steps:\n      - with: {note: 'a #', permission-checks: write}\n"),
            ["quoted-input.yml:a"],
        ),
        "token-quoted.yml": (wf(a=token + "          permission-checks: 'write'\n"), ["token-quoted.yml:a"]),
        "token-checks.yml": (wf(a=token + "          permission-checks: write\n"), ["token-checks.yml:a"]),
        # Any part of jobs: this parser did not consume fails closed.
        "flow-job.yml": (
            wf(reader="    steps: []\n") + "  writer: {runs-on: x, permissions: {checks: write}, steps: []}\n",
            ["flow-job.yml:?"],
        ),
        "key-comment.yml": (
            wf(reader="    steps: []\n") + "  writer:  # reconciles\n    steps:\n"
            "      - run: python3 -m mandate.receipt reconcile\n",
            ["key-comment.yml:writer"],
        ),
        "after-jobs.yml": (wf(reader="    steps: []\n") + "permissions:\n  checks: write\n", ["after-jobs.yml:?"]),
        # Only workflow- or job-level concurrency serializes; a nested mapping does not.
        "nested.yml": (
            wf(writer="    permissions:\n      checks: write\n    strategy:\n      matrix:\n"
               "        concurrency:\n"
               f"          group: {group}\n          cancel-in-progress: false\n"),
            ["nested.yml:writer"],
        ),
        "job-write-all.yml": (wf(a="    permissions: write-all\n"), ["job-write-all.yml:a"]),
        # An App token minted without permission inputs carries every App
        # permission, which for the Mandate App includes checks: write.
        "token.yml": (wf(a=token), ["token.yml:a"]),
        "scoped.yml": (wf(a=token + "          permission-contents: write\n"), []),
        "two-tokens.yml": (
            wf(a=token + "          permission-contents: write\n" + token.replace("    steps:\n", "")),
            ["two-tokens.yml:a"],
        ),
        "tests.yml": (wf(a="    steps:\n      - run: python3 mandate/tests/test_receipt.py\n"), []),
        "odd.yml": ("jobs:\n    a:\n        steps:\n          - run: python3 -m mandate.receipt\n", ["odd.yml:?"]),
    }
    for name, (text, expected) in cases.items():
        assert r.serial_violations({name: text}) == expected, (name, r.serial_violations({name: text}))
    folder = ROOT / ".github" / "workflows"
    workflows = {w.name: w.read_text() for w in [*folder.glob("*.yml"), *folder.glob("*.yaml")]}
    assert len(workflows) > 10 and r.serial_violations(workflows) == [], r.serial_violations(workflows)

    # Codex F2: the summary fits GitHub's 65535-byte limit in UTF-8, cut on a
    # character boundary, with multibyte reason text. Shifting by 0-3 ASCII
    # bytes makes some variant's cut fall inside a multibyte character.
    for shift in range(4):
        many = m.Decision(
            "ESCALATE",
            tuple(m.reason(f"UNDELEGATED:c{i}", "x" * shift + "é€😀" * 100) for i in range(400)),
            (), (), POLICY, SUBJECT,
        )
        wide, big = FakeGit(), FakeChecks()
        did = put(wide, build(many), DELEG)[0]["decision_id"]
        r.reconcile_check(both(big, wide), REPO, REF, HEAD, app_id=APP, delegations=RESOLVE)
        summary = big.runs[0]["output"]["summary"]
        assert len(summary.encode("utf-8")) <= r.SUMMARY_LIMIT == 65535, len(summary.encode("utf-8"))
        assert len(summary) < 65535 and summary.endswith("more reasons in the receipt")
        assert "\ufffd" not in summary, f"shift {shift}: cut inside a multibyte character"

    # Merge trailers: final revalidation records the fresh decision, so the
    # trailers always name this decision's latest revision. Shadow grants nothing.
    tip = git.refs[REF]
    refused("CONTRACT_ERROR", functools.partial(r.trailers, after=None), git, REPO, REF, receipt["subject"], build(decision()), DELEG)
    subject = enforced(decision())["subject"]
    refused("CONTRACT_ERROR", functools.partial(r.trailers, after=None), git, REPO, REF, {**subject, "enforcement": "live"},
            build(decision(), enforcement="live"), DELEG)
    refused("CONTRACT_ERROR", functools.partial(r.trailers, after=None), git, REPO, REF, {**subject, "enforcement": ENF + "\n"},
            build(decision(), enforcement=ENF + "\n"), DELEG)
    assert git.refs[REF] == tip, "a refused revalidation records nothing"
    text = r.trailers(git, REPO, REF, subject, enforced(decision(), at="2026-10-22T00:00:00Z"), DELEG, after=r.pr_latest(git, REPO, REF, REPO, 7))
    authorized = json.loads(git.files(REF)[l.LEDGER].decode().splitlines()[-1])
    chain = authorized["entry_digest"]
    assert authorized["receipt_revision"] == "r1" and authorized["outcome"] == "AUTHORIZE"
    tip = git.refs[REF]
    assert r.trailers(git, REPO, REF, subject, enforced(decision(), at="2026-10-23T00:00:00Z"), DELEG, after=r.pr_latest(git, REPO, REF, REPO, 7)) == text
    assert git.refs[REF] == tip, "already the latest revision: revalidation appends nothing"
    parsed = r.parse_trailers("Merge pull request #7\n\nbody\n\n" + text)
    assert parsed == {
        "Mandate-Decision": authorized["decision_id"],
        "Mandate-Receipt-Digest": authorized["receipt_digest"],
        "Mandate-Chain-Head": chain,
    }, parsed

    # A stale worker holding a superseded AUTHORIZE r1 (r2 since escalated)
    # gets trailers for a new latest revision, never for r1.
    stale = FakeGit()
    old, _, _ = put(stale, enforced(decision()), DELEG)
    put(stale, enforced(decision("ESCALATE")), DELEG)
    fresh = r.parse_trailers(r.trailers(stale, REPO, REF, subject, enforced(decision()), DELEG, after=r.pr_latest(stale, REPO, REF, REPO, 7)))
    latest = json.loads(stale.files(REF)[l.LEDGER].decode().splitlines()[-1])
    assert latest["receipt_revision"] == "r3" and latest["outcome"] == "AUTHORIZE"
    assert fresh["Mandate-Receipt-Digest"] == latest["receipt_digest"] != old["receipt_digest"]

    # Refusals: not AUTHORIZE now, or the subject drifted since the worker acted.
    tip = git.refs[REF]
    refused("CONTRACT_ERROR", functools.partial(r.trailers, after=None), git, REPO, REF, subject, enforced(decision("ESCALATE")), DELEG)
    moved = enforced(decision(subject=e.Subject(REPO, "c" * 40, BASE, POLICY)))
    refused("HEAD_CHANGED", functools.partial(r.trailers, after=None), git, REPO, REF, subject, moved, DELEG)
    rebased = enforced(decision(subject=e.Subject(REPO, HEAD, "c" * 40, POLICY)))
    refused("BASE_CHANGED", functools.partial(r.trailers, after=None), git, REPO, REF, subject, rebased, DELEG)
    drifted = build(decision(), enforcement="sha256:" + "f" * 64)
    refused("ENFORCEMENT_DRIFT", functools.partial(r.trailers, after=None), git, REPO, REF, subject, drifted, DELEG)
    refused("CONTRACT_ERROR", functools.partial(r.trailers, after=None), git, REPO, REF, {**subject, "pull_request": 8}, enforced(decision()), DELEG)
    assert git.refs[REF] == tip, "a refused revalidation records nothing"
    # Only the final paragraph holds trailers; body text cannot supply or spoil them.
    quoted = "Merge\n\n" + text.replace(chain, "sha256:" + "8" * 64) + "\n\nbody\n\n" + text
    assert r.parse_trailers(quoted) == parsed, r.parse_trailers(quoted)
    assert r.parse_trailers("Merge\n\n" + text + "\n\nSigned-off-by: x") is None
    assert r.parse_trailers("no trailers") is None
    assert r.parse_trailers(text + "\n" + text) is None, "duplicate trailers are ambiguous"

    # Offline audit against merge-commit anchors only (checks may have expired).
    ledger_text = git.files(REF)[l.LEDGER].decode()
    stored_receipts = receipts(git)
    anchor = r.parse_trailers(text)
    # The anchor is the visible tip, yet a truncated tail after it would look
    # the same, so the limit is still stated.
    failures, limits = r.audit(ledger_text, stored_receipts, [anchor])
    assert failures == [] and limits == [
        (
            "0 entries visible after the last anchor: truncation, rewrite or forged "
            "appends (key compromise) after it are not detectable with available anchor"
        )
    ], (failures, limits)

    lines = ledger_text.splitlines()
    # Middle deletion: the chain breaks.
    failures, _ = r.audit("\n".join([lines[0], lines[2]]) + "\n", stored_receipts, [anchor])
    assert any("chain break" in f for f in failures), failures
    # Tail truncation below the anchor: the anchor no longer resolves.
    failures, _ = r.audit("\n".join(lines[:2]) + "\n", stored_receipts, [anchor])
    assert any("truncated or rewritten" in f for f in failures), failures
    # Full rewrite: a fresh, self-consistent chain without the anchored entry.
    rewrite = FakeGit()
    put(rewrite, build(decision("ESCALATE")), DELEG)
    failures, _ = r.audit(rewrite.files(REF)[l.LEDGER].decode(), receipts(rewrite), [anchor])
    assert any("truncated or rewritten" in f for f in failures), failures
    # An anchor whose receipt digest is not the one recorded for its decision.
    forged = {**anchor, "Mandate-Receipt-Digest": "sha256:" + "9" * 64}
    failures, _ = r.audit(ledger_text, stored_receipts, [forged])
    assert any("not recorded at or before" in f for f in failures), failures
    # An anchor whose receipt was recorded only after its chain head.
    early = {**anchor, "Mandate-Chain-Head": first["entry_digest"]}
    failures, _ = r.audit(ledger_text, stored_receipts, [early])
    assert any("not recorded at or before" in f for f in failures), failures
    # Key compromise: a key holder appends well-formed entries after the last
    # anchor. Nothing is broken, so the audit must say it cannot tell.
    put(git, build(decision(subject=e.Subject(REPO, "e" * 40, BASE, POLICY))), DELEG)
    failures, limits = r.audit(git.files(REF)[l.LEDGER].decode(), receipts(git), [anchor])
    assert failures == [] and limits == [
        (
            "1 entry visible after the last anchor: truncation, rewrite or forged "
            "appends (key compromise) after it are not detectable with available anchor"
        )
    ], (failures, limits)
    # No anchor at all: nothing about truncation or rewrite can be claimed.
    _, limits = r.audit(ledger_text, stored_receipts, [])
    assert limits and "not detectable with available anchor" in limits[0], limits

    print("receipt tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
