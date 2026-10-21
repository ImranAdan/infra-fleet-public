"""Receipt checks (KAN-26). Run: python3 mandate/tests/test_receipt.py

Real decide() output becomes a versioned receipt, recorded through the real
ledger.append() against the fast-forward-only FakeGit from test_ledger. The
check-run publisher runs against a fake checks API. Nothing calls GitHub.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from test_ledger import REF, REPO, FakeGit, receipts  # noqa: E402

from mandate import decision as m  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import ledger as l  # noqa: E402
from mandate import receipt as r  # noqa: E402

HEAD, BASE = "a" * 40, "b" * 40
POLICY = "ImranAdan/mandate-delegation@" + "d" * 40 + ":repositories/r.toml"
SUBJECT = e.Subject(REPO, HEAD, BASE, POLICY)
VERSIONS = {"package": "0.1.0", "adapter": 1}
ACTORS = {"app_id": 5336871}


def decision(outcome: str = "AUTHORIZE", subject: e.Subject = SUBJECT) -> m.Decision:
    reasons = () if outcome == "AUTHORIZE" else (m.reason("UNCLASSIFIED", "x.py"),)
    return m.Decision(outcome, reasons, (), (), POLICY, subject)


def build(dec: m.Decision, at: str = "2026-10-21T00:00:00Z", enforcement: str = "shadow") -> dict:
    return r.build(dec, 7, enforcement, versions=VERSIONS, actors=ACTORS, evaluated_at=at)


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

    def __call__(self, method: str, path: str, payload):
        if method == "GET":
            # Like GitHub: filter defaults to latest (newest run per suite; one
            # suite here), and pages are short, so callers must page by total.
            runs = [dict(x) for x in self.runs if x["head_sha"] in path]
            if "filter=all" not in path:
                runs = runs[-1:]
            page = int(re.search(r"[?&]page=(\d+)", path).group(1)) if "page=" in path else 1
            return {"total_count": len(runs), "check_runs": runs[page - 1 : page]}
        if self.before_write:
            racer, self.before_write = self.before_write, None
            racer()
        self.writes += 1
        self.shown.append((payload["conclusion"], payload["output"]["title"]))
        # GitHub echoes output with keys the payload never sends.
        output = {**payload["output"], "text": None, "annotations_count": 0}
        if method == "POST":
            self.runs.append({**payload, "output": output, "id": len(self.runs) + 1})
            return self.runs[-1]
        run = next(x for x in self.runs if path.endswith(f"/check-runs/{x['id']}"))
        run.update({**payload, "output": output})
        return run


def both(checks: FakeChecks, git: FakeGit):
    """One provider: check-run calls go to the checks fake, the rest to Git."""
    return lambda method, path, payload: (checks if "check-runs" in path else git)(
        method, path, payload
    )


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
    first, head1, appended = r.record(git, REPO, REF, receipt)
    assert appended and first["receipt_revision"] == "r1" and first["seq"] == 0
    assert head1 == first["entry_digest"]
    tip = git.refs[REF]
    again, head2, appended = r.record(git, REPO, REF, build(decision(), at="2026-10-21T09:00:00Z"))
    assert not appended and again == first and head2 == head1 and git.refs[REF] == tip

    # A changed outcome under the same subject is the next revision, same ID;
    # flipping back is a third revision, never a reuse of r1.
    second, _, appended = r.record(git, REPO, REF, build(decision("ESCALATE")))
    assert appended and second["receipt_revision"] == "r2"
    assert second["decision_id"] == first["decision_id"]
    third, _, appended = r.record(git, REPO, REF, build(decision()))
    assert appended and third["receipt_revision"] == "r3"

    # Receipts are canonical, versioned and name their own revision.
    stored = json.loads(receipts(git)[l.receipt_path(first["decision_id"], "r2")])
    assert stored["receipt_revision"] == "r2" and stored["decision"]["outcome"] == "ESCALATE"
    assert l.verify(git.files(REF)[l.LEDGER].decode(), receipts(git)) == []

    # A concurrent writer that takes the same revision first: re-read, take the next.
    race = FakeGit()
    other = build(decision(subject=e.Subject(REPO, "f" * 40, BASE, POLICY)))
    race.before_advance = lambda: r.record(race, REPO, REF, other)
    mine, _, appended = r.record(race, REPO, REF, receipt)
    assert appended and mine["seq"] == 1, mine

    # A concurrent writer takes this decision's next revision first: re-read, take the one after.
    same = FakeGit()
    same.before_advance = lambda: r.record(same, REPO, REF, build(decision("ESCALATE")))
    mine, _, appended = r.record(same, REPO, REF, receipt)
    assert appended and mine["receipt_revision"] == "r2" and mine["seq"] == 1, mine

    # A tampered receipt is never trusted for the no-op comparison, even when
    # it still says the same thing (re-serialized, so its digest differs).
    for tampered in (b'{"x":1}', json.dumps({**receipt, "receipt_revision": "r1"}, indent=1).encode()):
        bad = FakeGit()
        r.record(bad, REPO, REF, receipt)
        path = l.receipt_path(receipt["decision_id"], "r1")
        bad.objects[bad.objects[bad.refs[REF]]["tree"]]["files"][path] = tampered
        refused("LEDGER_INVALID", r.record, bad, REPO, REF, receipt)

    # Check run: the reconciler shows the ledger's latest revision for a
    # decision; nothing the caller holds can choose the revision.
    did = receipt["decision_id"]
    checks = FakeChecks()
    api = both(checks, git)
    r.reconcile_check(api, REPO, REF, did, shadow=True)
    r.reconcile_check(api, REPO, REF, did, shadow=True)
    assert checks.writes == 1 and len(checks.runs) == 1
    run = checks.runs[0]
    assert run["name"] == r.CHECK_NAME == "mandate/decision"
    assert run["external_id"] == did and run["conclusion"] == "neutral"
    assert third["receipt_digest"] in run["output"]["summary"] and "r3" in run["output"]["title"]
    r.reconcile_check(api, REPO, REF, did, shadow=False)
    assert checks.writes == 2 and visible(checks) == [("success", "AUTHORIZE (r3)")]

    # Codex F1 interleaving: a delayed publisher read r2 AUTHORIZE; before its
    # write lands, r3 ESCALATE is recorded and shown. The delayed write happens
    # (stale success), then it re-reads the ledger and restores r3.
    lg, ck = FakeGit(), FakeChecks()
    api2 = both(ck, lg)
    r.record(lg, REPO, REF, build(decision("ESCALATE")))
    r.reconcile_check(api2, REPO, REF, did, shadow=False)
    r.record(lg, REPO, REF, build(decision()))

    def newer() -> None:
        r.record(lg, REPO, REF, build(decision("ESCALATE"), at="2026-10-21T01:00:00Z"))
        r.reconcile_check(api2, REPO, REF, did, shadow=False)

    ck.before_write = newer
    r.reconcile_check(api2, REPO, REF, did, shadow=False)
    assert ("success", "AUTHORIZE (r2)") in ck.shown, ck.shown  # the race really ran
    assert visible(ck) == [("failure", "ESCALATE (r3)")], visible(ck)

    # The same race on first publication creates two runs; both end at the latest.
    lg2, ck2 = FakeGit(), FakeChecks()
    api3 = both(ck2, lg2)
    r.record(lg2, REPO, REF, build(decision()))
    ck2.before_write = lambda: (
        r.record(lg2, REPO, REF, build(decision("ESCALATE"))),
        r.reconcile_check(api3, REPO, REF, did, shadow=False),
    )
    r.reconcile_check(api3, REPO, REF, did, shadow=False)
    assert visible(ck2) == [("failure", "ESCALATE (r2)")] * 2, visible(ck2)
    # A later revision reaches both duplicates, not just the newest one.
    r.record(lg2, REPO, REF, build(decision()))
    r.reconcile_check(api3, REPO, REF, did, shadow=False)
    assert visible(ck2) == [("success", "AUTHORIZE (r3)")] * 2, visible(ck2)

    # Single writer per pull request: every job that records receipts or can
    # write checks runs in the one canonical per-PR group, without cancelling.
    group = r.CANONICAL_GROUP
    assert group == "mandate-decision-${{ github.repository }}-${{ inputs.pr }}"

    def wf(head: str = "", **jobs: str) -> str:
        return "on: workflow_call\n" + head + "jobs:\n" + "".join(
            f"  {name}:\n    runs-on: ubuntu-latest\n{body}" for name, body in jobs.items()
        )

    serial = f"    concurrency:\n      group: {group}\n      cancel-in-progress: false\n"
    write = "    steps:\n      - run: python3 -m mandate.receipt reconcile\n"
    top = f"concurrency:\n  group: '{group}'\n  cancel-in-progress: false\n"
    cases = {
        "job.yml": (wf(writer=serial + write), []),
        "top.yml": (wf(top, writer=write), []),
        "bare.yml": (wf(writer=write), ["bare.yml:writer"]),
        "other-job.yml": (wf(reader=serial, writer=write), ["other-job.yml:writer"]),
        "suffix.yml": (wf(writer=serial.replace("inputs.pr", "github.run_id") + write), ["suffix.yml:writer"]),
        "cancel.yml": (wf(writer=serial.replace("false", "true") + write), ["cancel.yml:writer"]),
        "checks.yml": (wf("permissions:\n  checks: write\n", a="    steps: []\n"), ["checks.yml:a"]),
        "job-checks.yml": (wf(a="    permissions:\n      checks: write\n"), ["job-checks.yml:a"]),
        "inline.yml": (wf(a="    steps:\n      - run: python3 -c 'from mandate import receipt'\n"), ["inline.yml:a"]),
        "app.yml": (wf(a="    steps:\n      - with:\n          permission-checks: write\n"), ["app.yml:a"]),
        "path.yml": (wf(a="    steps:\n      - run: python3 mandate/src/mandate/receipt.py\n"), ["path.yml:a"]),
        "read.yml": (wf("permissions:\n  checks: read\n", a="    steps: []\n"), []),
        "tests.yml": (wf(a="    steps:\n      - run: python3 mandate/tests/test_receipt.py\n"), []),
        "odd.yml": ("jobs:\n    a:\n        steps:\n          - run: python3 -m mandate.receipt\n", ["odd.yml:?"]),
    }
    for name, (text, expected) in cases.items():
        assert r.serial_violations({name: text}) == expected, (name, r.serial_violations({name: text}))
    workflows = {w.name: w.read_text() for w in (ROOT / ".github" / "workflows").glob("*.yml")}
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
        r.record(wide, REPO, REF, build(many))
        r.reconcile_check(both(big, wide), REPO, REF, did, shadow=True)
        summary = big.runs[0]["output"]["summary"]
        assert len(summary.encode("utf-8")) <= r.SUMMARY_LIMIT == 65535, len(summary.encode("utf-8"))
        assert len(summary) < 65535 and summary.endswith("more reasons in the receipt")
        assert "\ufffd" not in summary, f"shift {shift}: cut inside a multibyte character"

    # Merge trailers: final revalidation records the fresh decision, so the
    # trailers always name this decision's latest revision.
    subject = receipt["subject"]
    tip = git.refs[REF]
    text = r.trailers(git, REPO, REF, subject, build(decision(), at="2026-10-22T00:00:00Z"))
    assert git.refs[REF] == tip, "r3 already says AUTHORIZE: revalidation appends nothing"
    chain = json.loads(git.files(REF)[l.LEDGER].decode().splitlines()[-1])["entry_digest"]
    parsed = r.parse_trailers("Merge pull request #7\n\nbody\n\n" + text)
    assert parsed == {
        "Mandate-Decision": third["decision_id"],
        "Mandate-Receipt-Digest": third["receipt_digest"],
        "Mandate-Chain-Head": chain,
    }, parsed

    # A stale worker holding a superseded AUTHORIZE r1 (r2 since escalated)
    # gets trailers for a new latest revision, never for r1.
    stale = FakeGit()
    old, _, _ = r.record(stale, REPO, REF, receipt)
    r.record(stale, REPO, REF, build(decision("ESCALATE")))
    fresh = r.parse_trailers(r.trailers(stale, REPO, REF, subject, build(decision())))
    latest = json.loads(stale.files(REF)[l.LEDGER].decode().splitlines()[-1])
    assert latest["receipt_revision"] == "r3" and latest["outcome"] == "AUTHORIZE"
    assert fresh["Mandate-Receipt-Digest"] == latest["receipt_digest"] != old["receipt_digest"]

    # Refusals: not AUTHORIZE now, or the subject drifted since the worker acted.
    tip = git.refs[REF]
    refused("CONTRACT_ERROR", r.trailers, git, REPO, REF, subject, build(decision("ESCALATE")))
    moved = build(decision(subject=e.Subject(REPO, "c" * 40, BASE, POLICY)))
    refused("HEAD_CHANGED", r.trailers, git, REPO, REF, subject, moved)
    rebased = build(decision(subject=e.Subject(REPO, HEAD, "c" * 40, POLICY)))
    refused("BASE_CHANGED", r.trailers, git, REPO, REF, subject, rebased)
    refused("ENFORCEMENT_DRIFT", r.trailers, git, REPO, REF, subject, build(decision(), enforcement="sha256:e"))
    refused("CONTRACT_ERROR", r.trailers, git, REPO, REF, {**subject, "pull_request": 8}, build(decision()))
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
    r.record(rewrite, REPO, REF, build(decision("ESCALATE")))
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
    r.record(git, REPO, REF, build(decision(subject=e.Subject(REPO, "e" * 40, BASE, POLICY))))
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
