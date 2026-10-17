"""Evidence checks (KAN-18). Run: python3 mandate/tests/test_evidence.py

Fixture-level only: the GitHub objects below are shaped like the REST API's
check-run and workflow-run responses, not fetched live.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402

REPO = "ImranAdan/infra-fleet-public"
HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40
POLICY = f"{d.DELEGATION_REPOSITORY}@{'d' * 40}:repositories/infra-fleet-public.toml"
DELEGATION = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text(), REPO, POLICY)
SUBJECT = e.Subject(repository=REPO, head_sha=HEAD, base_sha=BASE, policy=POLICY)
INTENT = "Intent gate / Declared intent"


def run(
    run_id: int = 7,
    *,
    path: str = ".github/workflows/intent-gate.yml",
    event: str = "pull_request",
    head: str = HEAD,
    base: str = BASE,
    attempt: int = 1,
    suite: int | None = None,
) -> dict:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "check_suite_id": suite or run_id * 10,
        "path": path,
        "event": event,
        "head_sha": head,
        "head_branch": "feature",
        "repository": {"full_name": REPO},
        "pull_requests": [{"number": 1, "head": {"sha": head}, "base": {"sha": base}}],
    }


def check(
    check_id: int = 70,
    *,
    name: str = INTENT,
    conclusion: str | None = "success",
    app_id: int = e.ACTIONS_APP_ID,
    suite: int = 70,
    head: str = HEAD,
) -> dict:
    return {
        "id": check_id,
        "name": name,
        "head_sha": head,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "started_at": "2026-10-17T10:00:00Z",
        "completed_at": "2026-10-17T10:01:00Z" if conclusion else None,
        "app": {"id": app_id, "slug": "github-actions" if app_id == e.ACTIONS_APP_ID else "other"},
        "check_suite": {"id": suite},
    }


def codes(records: list[e.EvidenceRecord], require: tuple[str, ...] = ("intent-gate",)) -> list[str]:
    return [code for code, _ in e.evaluate(DELEGATION, require, records, SUBJECT).failures]


def main() -> int:
    good = e.normalize(check(), run(), SUBJECT)

    # Normalized facts keep the raw provider IDs and the exact subject.
    assert (good.check_run_id, good.check_suite_id, good.run_id, good.run_attempt) == (70, 70, 7, 1)
    assert (good.workflow, good.event, good.app_id) == (".github/workflows/intent-gate.yml", "pull_request", 15368)
    assert (good.head_sha, good.base_sha, good.policy, good.repository) == (HEAD, BASE, POLICY, REPO)
    result = e.evaluate(DELEGATION, ("intent-gate",), [good], SUBJECT)
    assert result.failures == () and result.accepted == (("intent-gate", (good,)),), result

    # Receipt evidence round-trips through JSON without PR prose (exit evidence).
    data = json.loads(json.dumps(good.to_dict(), sort_keys=True))
    assert e.EvidenceRecord.from_dict(data) == good and data["version"] == 1
    try:
        e.EvidenceRecord.from_dict({**data, "verification_prose": "trust me"})
    except ValueError:
        pass
    else:
        raise AssertionError("from_dict accepted an unknown field")

    # A-24 / A-5: the same check name from another workflow, event or App.
    for wrong in (
        e.normalize(check(), run(path=".github/workflows/forged.yml"), SUBJECT),
        e.normalize(check(), run(event="workflow_dispatch"), SUBJECT),
        e.normalize(check(app_id=999), run(), SUBJECT),
    ):
        assert codes([wrong]) == ["CHECK_WRONG_SOURCE", "EVIDENCE_REQUIRED:intent-gate"], (wrong, codes([wrong]))
    # A forged twin still blocks while the genuine producer passes.
    forged = e.normalize(check(71, suite=80), run(8, path=".github/workflows/forged.yml"), SUBJECT)
    assert codes([good, forged]) == ["CHECK_WRONG_SOURCE"]
    assert e.evaluate(DELEGATION, ("intent-gate",), [good, forged], SUBJECT).accepted == ()
    # A check run that belongs to a different workflow run is not correlated to it.
    assert e.normalize(check(suite=999), run(), SUBJECT).workflow is None

    # Applicability: right producer, wrong subject.
    for stale in (
        e.normalize(check(head=OTHER), run(head=OTHER), SUBJECT),
        e.normalize(check(), run(base=OTHER), SUBJECT),
        e.normalize(check(), {**run(), "repository": {"full_name": "ImranAdan/fork"}}, SUBJECT),
        e.normalize(check(), run(), e.Subject(REPO, HEAD, BASE, POLICY.replace("d" * 40, "e" * 40))),
    ):
        assert codes([stale]) == ["EVIDENCE_REQUIRED:intent-gate"], (stale, codes([stale]))
    assert e.applicability(good, SUBJECT) == ()
    assert e.applicability(e.normalize(check(), run(base=OTHER), SUBJECT), SUBJECT) == ("BASE",)

    # A-17: authentic, current, green, but not what the class requires.
    lint = e.normalize(check(72, name="lint", suite=90), run(9, path=".github/workflows/lint.yml"), SUBJECT)
    assert codes([lint]) == ["EVIDENCE_REQUIRED:intent-gate"]

    # A-4: prose is not an input, so with no check nothing is satisfied.
    assert codes([]) == ["EVIDENCE_REQUIRED:intent-gate"]

    # A-20: conflicting current results, or a same-name result from no known run.
    failed = e.normalize(check(73, conclusion="failure", suite=100), run(10), SUBJECT)
    assert codes([good, failed]) == ["EVIDENCE_CONFLICT"]
    unknown = e.normalize(check(74, suite=110), None, SUBJECT)
    assert codes([good, unknown]) == ["EVIDENCE_CONFLICT"]

    # Reruns: the latest attempt of one run supersedes the earlier one.
    rerun = e.normalize(check(75, suite=70), run(attempt=2), SUBJECT)
    first_failed = e.normalize(check(76, conclusion="failure", suite=70), run(), SUBJECT)
    assert codes([first_failed, rerun]) == []
    assert codes([failed]) == ["EVIDENCE_FAILED:intent-gate"]
    assert codes([e.normalize(check(conclusion=None), run(), SUBJECT)]) == ["EVIDENCE_PENDING:intent-gate"]

    # Requirements the delegation never declared cannot be satisfied.
    assert codes([good], ("nonexistent",)) == ["EVIDENCE_UNDECLARED:nonexistent"]

    print("evidence tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
