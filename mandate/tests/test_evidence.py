"""Evidence checks. Run: python3 mandate/tests/test_evidence.py

Fixture-level only: the GitHub objects below are shaped like the REST API's
check-run, workflow-run, job, job-log and git-commit responses, not fetched
live. The log lines copy the real runner's input echo of a gate run.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402

REPO = "ImranAdan/infra-fleet-public"
HEAD, BASE, OTHER, MERGE = "a" * 40, "b" * 40, "c" * 40, "f" * 40
POLICY = f"{d.DELEGATION_REPOSITORY}@{'d' * 40}:repositories/infra-fleet-public.toml"
DELEGATION = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text(), REPO, POLICY)
SUBJECT = e.Subject(repository=REPO, head_sha=HEAD, base_sha=BASE, policy=POLICY)
INTENT = "Intent gate / Declared intent"
CALLER, SHARED = ".github/workflows/intent-gate.yml", ".github/workflows/intent-gate-run.yml"
OK = e.Tested(BASE, MERGE, None)
ACTION = "ImranAdan/infra-fleet-advisor-public/.github/actions/intent-gate@" + "7" * 40
COMPARE = "Compare declared intent at base and merge result"
# The gate's workflows as Fleet runs them (comments trimmed).
CALLER_SOURCE = """name: Intent Gate
on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]
permissions:
  contents: read
jobs:
  intent:
    name: Intent gate
    uses: ./.github/workflows/intent-gate-run.yml
"""


def shared_source(action: str = ACTION, name: str = COMPARE, extra: str = "") -> str:
    return f"""name: Intent Gate (shared)
on:
  workflow_call:
permissions:
  contents: read
jobs:
  gate:
    name: Declared intent
    runs-on: ubuntu-latest
    steps:
      - name: Checkout the merge result with history
        uses: actions/checkout@{"3" * 40} # v7.0.1
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Resolve the compared commits
        id: commits
        run: |
          echo "base=$(git rev-parse HEAD^1)" >> "$GITHUB_OUTPUT"
          echo "head=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
      - name: {name}
        uses: {action}
        with:
          base-sha: ${{{{ steps.commits.outputs.base }}}}
          head-sha: ${{{{ steps.commits.outputs.head }}}}
{extra}"""


SHARED_SOURCE = shared_source()


def run(
    run_id: int = 7,
    *,
    path: str = ".github/workflows/intent-gate.yml",
    event: str = "pull_request",
    head: str = HEAD,
    base: str = BASE,
    attempt: int = 1,
    suite: int | None = None,
    merge: str = MERGE,
) -> dict:
    """The association names ``base``, which proves nothing (open PRs only)."""
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
        "referenced_workflows": [{"path": f"{REPO}/{SHARED}@{merge}", "sha": merge, "ref": "refs/pull/1/merge"}],
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


def log(base: str = BASE, merge: str = MERGE, action: str = ACTION) -> str:
    """The runner's echo of the comparing step's inputs, as in a real gate job log."""
    return (
        "2026-10-28T21:45:44.1662541Z ##[group]Run echo \"base=$(git rev-parse HEAD^1)\" >> \"$GITHUB_OUTPUT\"\n"
        "2026-10-28T21:45:44.1701068Z ##[endgroup]\n"
        f"2026-10-28T21:45:44.1955212Z ##[group]Run {action}\n"
        "2026-10-28T21:45:44.1955926Z with:\n"
        f"2026-10-28T21:45:44.1956250Z   base-sha: {base}\n"
        f"2026-10-28T21:45:44.1956686Z   head-sha: {merge}\n"
        "2026-10-28T21:45:44.1957288Z   fleet-path: .\n"
        "2026-10-28T21:45:44.1957569Z ##[endgroup]\n"
        # The action's own step then echoes its environment, uppercase.
        "2026-10-28T21:45:47.2369224Z env:\n"
        f"2026-10-28T21:45:47.2372245Z   BASE_SHA: {base}\n"
        f"2026-10-28T21:45:47.2372584Z   HEAD_SHA: {merge}\n"
    )


def observations(*, head: str = HEAD, base: str = BASE, merge: str = MERGE, run_id: int = 7, attempt: int = 1,
                 check_id: int = 70, job: int = 70, repo: str = REPO, compare: str | None = "success") -> dict[str, str]:
    """REST path -> exact response text the capture reads for ``job``, a job
    whose URL names check run ``check_id`` and whose comparing step concluded
    ``compare`` (None: the job lists no such step)."""
    steps = [{"number": 1, "name": "Set up job", "conclusion": "success"},
             *([{"number": 4, "name": COMPARE, "conclusion": compare}] if compare else [])]
    return {
        f"actions/jobs/{job}": json.dumps({"id": job, "run_id": run_id, "run_attempt": attempt, "head_sha": head,
                                           "check_run_url": f"https://api.github.com/repos/{repo}/check-runs/{check_id}",
                                           "steps": steps}),
        f"actions/jobs/{job}/logs": log(base, merge),
        f"git/commits/{merge}": json.dumps({"sha": merge, "parents": [{"sha": base}, {"sha": head}]}),
    }


def sources(*shas: str, shared: str = SHARED_SOURCE) -> dict[tuple[str, str], str]:
    """(commit, path) -> the producer workflows' text at each commit."""
    return {(sha, path): text for sha in shas for path, text in ((CALLER, CALLER_SOURCE), (SHARED, shared))}


def capture(responses=None, files=None, *, check_run=None, workflow_run=...) -> e.Tested:
    """The real capture over canned observations."""
    responses = observations() if responses is None else responses
    files = sources(BASE, MERGE) if files is None else files
    return e.tested(check_run or check(), run() if workflow_run is ... else workflow_run,
                    responses.get, lambda sha: lambda path: files.get((sha, path)))


def codes(records: list[e.EvidenceRecord], require: tuple[str, ...] = ("intent-gate",)) -> list[str]:
    return [code for code, _ in e.evaluate(DELEGATION, require, records, SUBJECT).failures]


def main() -> int:
    good = e.normalize(check(), run(), SUBJECT, OK)

    # Normalized facts keep the raw provider IDs and the exact subject. The
    # check's head is the PR head; the compared commit is its merge into the base.
    assert (good.check_run_id, good.check_suite_id, good.run_id, good.run_attempt) == (70, 70, 7, 1)
    assert (good.workflow, good.event, good.app_id) == (".github/workflows/intent-gate.yml", "pull_request", 15368)
    assert (good.head_sha, good.base_sha, good.policy, good.repository) == (HEAD, BASE, POLICY, REPO)
    assert (good.compared_sha, good.unproven) == (MERGE, None)
    result = e.evaluate(DELEGATION, ("intent-gate",), [good], SUBJECT)
    assert result.failures == () and result.accepted == (("intent-gate", (good,)),), result

    # Receipt evidence round-trips through JSON without PR prose (exit evidence).
    data = json.loads(json.dumps(good.to_dict(), sort_keys=True))
    assert e.EvidenceRecord.from_dict(data) == good and data["version"] == 2
    try:
        e.EvidenceRecord.from_dict({**data, "verification_prose": "trust me"})
    except ValueError:
        pass
    else:
        raise AssertionError("from_dict accepted an unknown field")
    # A version 1 record took its base from the PR association; it is refused,
    # never read as a captured one.
    v1 = {k: v for k, v in data.items() if k not in ("compared_sha", "unproven")}
    for old in (v1, {**v1, "version": 1}, {**data, "version": 1}):
        try:
            e.EvidenceRecord.from_dict(old)
        except ValueError:
            pass
        else:
            raise AssertionError(f"from_dict accepted {old}")
    # A pull_request proof is whole or absent: a base with its compared merge
    # and no reason, or neither with the reason. Nothing else can be built or
    # read back, so no such record reaches evaluate() or a receipt.
    unknown = e.normalize(check(), run(), SUBJECT, e.Tested(None, None, "job 70 is unavailable"))
    assert e.EvidenceRecord.from_dict(json.loads(json.dumps(unknown.to_dict()))) == unknown
    for name, change in (("no compared merge", {"compared_sha": None}),
                         ("a declared failure", {"unproven": "capture did not prove a base"}),
                         ("a merge without a base", {"base_sha": None}),
                         ("an empty reason", {"base_sha": None, "compared_sha": None, "unproven": ""})):
        for build in (lambda: e.EvidenceRecord.from_dict({**data, **change}),
                      lambda: dataclasses.replace(good, **change),
                      lambda: e.normalize(check(), run(), SUBJECT, e.Tested(*({**good.to_dict(), **change}[k] for k in (
                          "base_sha", "compared_sha", "unproven"))))):
            try:
                build()
            except ValueError:
                pass
            else:
                raise AssertionError(f"built a record with {name}")
    for version in (3, "2", True):
        try:
            e.EvidenceRecord.from_dict({**data, "version": version})
        except ValueError:
            pass
        else:
            raise AssertionError(f"from_dict accepted version {version!r}")
    # Every declared type is enforced; nullable fields still accept None.
    assert e.EvidenceRecord.from_dict({**data, "run_id": None, "conclusion": None}).run_id is None
    for field, value in (("check_run_id", None), ("run_id", "not-a-run-id"), ("app_id", True),
                         ("check", 7), ("head_sha", None), ("run_attempt", 1.0), ("policy", None)):
        try:
            e.EvidenceRecord.from_dict({**data, field: value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"from_dict accepted {field}={value!r}")

    # The same check name from another workflow, event or App.
    for wrong in (
        e.normalize(check(), run(path=".github/workflows/forged.yml"), SUBJECT, OK),
        e.normalize(check(), run(event="workflow_dispatch"), SUBJECT, OK),
        e.normalize(check(app_id=999), run(), SUBJECT, OK),
    ):
        assert codes([wrong]) == ["CHECK_WRONG_SOURCE", "EVIDENCE_REQUIRED:intent-gate"], (wrong, codes([wrong]))
    # A forged twin still blocks while the genuine producer passes.
    forged = e.normalize(check(71, suite=80), run(8, path=".github/workflows/forged.yml"), SUBJECT, OK)
    assert codes([good, forged]) == ["CHECK_WRONG_SOURCE"]
    assert e.evaluate(DELEGATION, ("intent-gate",), [good, forged], SUBJECT).accepted == ()
    # A stale forged result (older head) does not block current genuine evidence.
    stale_forged = e.normalize(check(77, suite=120, head=OTHER), run(12, path=".github/workflows/forged.yml", head=OTHER), SUBJECT, OK)
    assert codes([good, stale_forged]) == []
    # An unattributable result on an older head is not a conflict either.
    assert codes([good, e.normalize(check(78, suite=130, head=OTHER), None, SUBJECT, OK)]) == []
    # Without a suite ID on both sides there is no correlation.
    no_suite = {k: v for k, v in check().items() if k != "check_suite"}
    assert e.normalize(no_suite, {k: v for k, v in run().items() if k != "check_suite_id"}, SUBJECT, OK).run_id is None
    # A check run that belongs to a different workflow run is not correlated to it.
    assert e.normalize(check(suite=999), run(), SUBJECT, OK).workflow is None

    # Capture: the base and merge the gate compared, proven from the exact
    # provider observations of its own job, never from matching text alone.
    assert capture() == OK
    # A genuine comparison of another base, or of another head, is captured as
    # such and is about another subject.
    other_base = capture(observations(base=OTHER), sources(OTHER, MERGE))
    assert other_base == e.Tested(OTHER, MERGE, None), other_base
    other_head = capture(observations(head=OTHER), check_run=check(head=OTHER), workflow_run=run(head=OTHER))
    assert other_head == OK, other_head
    # Anything the contract cannot prove leaves the compared commits unknown.
    jobs, logs, commit = "actions/jobs/70", "actions/jobs/70/logs", f"git/commits/{MERGE}"
    without = lambda key: {k: v for k, v in observations().items() if k != key}  # noqa: E731
    forged = "2026-10-28T21:45:50.0000000Z   base-sha: " + BASE + "\n"
    one_merge = "run 7 records no single merge commit it ran from"
    not_merge = f"commit {MERGE} is not a merge of this head into a base"
    changed = f"producer {SHARED} differs from its version at the tested base"
    no_echo = f"job 70 log does not show exactly one comparison of {BASE}...{MERGE} by its comparing step"
    in_step = no_echo
    skipped = f"job 70 did not run its comparing step {COMPARE!r} to success"
    unsupported = "run 7 producer has no single supported comparing step"
    unproven = {
        # missing or expired sources
        "no correlated run": (capture(workflow_run=None), "no workflow run correlates to check run 70"),
        "job unavailable": (capture(without(jobs)), "job 70 is unavailable"),
        "log expired": (capture(without(logs)), "job 70 log is unavailable, expired or missing"),
        "merge commit unavailable": (capture(without(commit)), not_merge),
        "producer unreadable": (capture(files={}), f"producer {CALLER} differs from its version at the tested base"),
        # mixed run or attempt data
        "job from another attempt": (capture(observations(attempt=2)), "job 70 is not attempt 1 of run 7 for this check"),
        "job from another run": (capture(observations(run_id=8)), "job 70 is not attempt 1 of run 7 for this check"),
        "job for another check run": (capture(observations(check_id=71)), "job 70 is not attempt 1 of run 7 for this check"),
        "job on another head": (capture(observations(head=OTHER)), "job 70 is not attempt 1 of run 7 for this check"),
        "no merge recorded": (capture(workflow_run={**run(), "referenced_workflows": []}), one_merge),
        "two merges recorded": (capture(workflow_run={**run(), "referenced_workflows": [
            *run()["referenced_workflows"], {"path": f"{REPO}/{SHARED}@{OTHER}", "sha": OTHER, "ref": "refs/pull/1/merge"}]}),
            one_merge),
        "a branch, not a merge": (capture(workflow_run={**run(), "referenced_workflows": [
            {"path": f"{REPO}/{SHARED}@{MERGE}", "sha": MERGE, "ref": "refs/heads/main"}]}), one_merge),
        "a workflow from another repository": (capture(workflow_run={**run(), "referenced_workflows": [
            {"path": f"ImranAdan/fork/{SHARED}@{MERGE}", "sha": MERGE, "ref": "refs/pull/1/merge"}]}), one_merge),
        "a merge of another head": (capture({**observations(), commit: json.dumps(
            {"sha": MERGE, "parents": [{"sha": BASE}, {"sha": OTHER}]})}), not_merge),
        "not a merge": (capture({**observations(), commit: json.dumps({"sha": MERGE, "parents": [{"sha": BASE}]})}),
                        not_merge),
        "an octopus merge": (capture({**observations(), commit: json.dumps(
            {"sha": MERGE, "parents": [{"sha": BASE}, {"sha": HEAD}, {"sha": OTHER}]})}), not_merge),
        # misleading or spoofed context
        "producer changed by the change": (capture(files=sources(BASE) | sources(
            MERGE, shared=SHARED_SOURCE.replace("HEAD^1", "HEAD~5"))), changed),
        "log names other commits": (capture({**observations(), logs: log(OTHER, MERGE)}), no_echo),
        "a forged echo beside the real one": (capture({**observations(), logs: log() + forged}), no_echo),
        "matching text, no input echo": (capture({**observations(), logs: f"BASE_SHA: {BASE}\nHEAD_SHA: {MERGE}\n"}),
                                         no_echo),
        "an echo with no run behind it": (capture(workflow_run={**run(), "referenced_workflows": None}), one_merge),
        "an unparseable job": (capture({**observations(), jobs: "<html>"}), "job 70 is unavailable"),
        # The inputs count only inside the supported comparing step's own block.
        "echo lines stripped of their step": (capture({**observations(), logs: "".join(
            line + "\n" for line in log().splitlines() if "-sha: " in line and "_SHA" not in line)}), in_step),
        "another action's block": (capture({**observations(), logs: log(action="example/unrelated-action@" + "7" * 40)}),
                                   in_step),
        "a block without its inputs": (capture({**observations(), logs: log().replace(" with:\n", " inputs:\n")}),
                                       in_step),
        "the comparing step skipped": (capture(observations(compare="skipped")), skipped),
        "the comparing step absent from the job": (capture(observations(compare=None)), skipped),
        # Contract v1 knows one comparing step: the Intent Gate action pinned by SHA.
        "a producer with no supported step": (capture(files=sources(BASE, MERGE, shared=shared_source(
            action="example/unrelated-action@" + "7" * 40))), unsupported),
        "the action pinned by tag": (capture(files=sources(BASE, MERGE, shared=shared_source(
            action=ACTION.split("@")[0] + "@v1"))), unsupported),
        "two comparing steps": (capture(files=sources(BASE, MERGE, shared=shared_source(extra=f"""      - name: Again
        uses: {ACTION}
        with:
          base-sha: x
          head-sha: y
"""))), unsupported),
        "a comparing step without both inputs": (capture(files=sources(BASE, MERGE, shared=SHARED_SOURCE.replace(
            "          head-sha: ${{ steps.commits.outputs.head }}\n", ""))), unsupported),
        "an unparseable producer": (capture(files=sources(BASE, MERGE, shared="jobs: [\n")), unsupported),
    }
    for name, (got, why) in unproven.items():
        assert got == e.Tested(None, None, why), (name, got)
    # Output that quotes an echo mid-line is not an echo: it neither proves
    # nor clouds the comparison.
    quoted = f"2026-10-28T21:45:50.0000000Z said 2026-10-28T21:45:44.1956250Z   base-sha: {OTHER}\n"
    assert capture({**observations(), logs: log() + quoted}) == OK

    # Applicability: right producer, wrong subject.
    for stale in (
        e.normalize(check(head=OTHER), run(head=OTHER), SUBJECT, OK),
        e.normalize(check(), run(), SUBJECT, other_base),
        e.normalize(check(), {**run(), "repository": {"full_name": "ImranAdan/fork"}}, SUBJECT, OK),
        e.normalize(check(), run(), e.Subject(REPO, HEAD, BASE, POLICY.replace("d" * 40, "e" * 40)), OK),
    ):
        assert codes([stale]) == ["EVIDENCE_NOT_APPLICABLE:intent-gate"], (stale, codes([stale]))
    # The rejection names the provider IDs and the mismatched subject fields.
    detail = dict(e.evaluate(DELEGATION, ("intent-gate",), [e.normalize(check(), run(), SUBJECT, other_base)], SUBJECT).failures)
    assert detail["EVIDENCE_NOT_APPLICABLE:intent-gate"] == "'Intent gate / Declared intent' check run 70 (run 7) is about another BASE", detail
    # The base comes only from the capture: a PR association naming this base
    # proves nothing, so an unproven capture leaves it unknown, not another one.
    expired = unproven["log expired"][0]
    assert e.normalize(check(), run(base=BASE), SUBJECT, expired).base_sha is None
    assert e.normalize(check(), run(base=OTHER), SUBJECT, OK).base_sha == BASE
    detail = dict(e.evaluate(DELEGATION, ("intent-gate",), [e.normalize(check(), run(), SUBJECT, expired)], SUBJECT).failures)
    assert detail == {"EVIDENCE_NOT_APPLICABLE:intent-gate": "'Intent gate / Declared intent' check run 70 (run 7): "
                      "tested base is unknown (job 70 log is unavailable, expired or missing)"}, detail
    detail = dict(e.evaluate(DELEGATION, ("intent-gate",), [e.normalize(check(head=OTHER), run(head=OTHER), SUBJECT, expired)],
                             SUBJECT).failures)
    assert detail == {"EVIDENCE_NOT_APPLICABLE:intent-gate": "'Intent gate / Declared intent' check run 70 (run 7) is about "
                      "another HEAD; tested base is unknown (job 70 log is unavailable, expired or missing)"}, detail
    # A dispatch run never binds a base, so its missing base is not mentioned.
    dispatch = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text().replace(
        'event = "pull_request"', 'event = "workflow_dispatch"', 1), REPO, POLICY)
    stale = e.normalize(check(head=OTHER), run(event="workflow_dispatch", head=OTHER), SUBJECT,
                        e.Tested(None, None, one_merge))
    detail = dict(e.evaluate(dispatch, ("intent-gate",), [stale], SUBJECT).failures)
    assert detail == {"EVIDENCE_NOT_APPLICABLE:intent-gate": "'Intent gate / Declared intent' check run 70 (run 7) is about "
                      "another HEAD"}, detail
    assert e.applicability(good, SUBJECT) == ()
    assert e.applicability(e.normalize(check(), run(), SUBJECT, other_base), SUBJECT) == ("BASE",)

    # Authentic, current, green, but not what the class requires.
    lint = e.normalize(check(72, name="lint", suite=90), run(9, path=".github/workflows/lint.yml"), SUBJECT, OK)
    assert codes([lint]) == ["EVIDENCE_REQUIRED:intent-gate"]

    # Prose is not an input, so with no check nothing is satisfied.
    assert codes([]) == ["EVIDENCE_REQUIRED:intent-gate"]

    # Conflicting current results, or a same-name result from no known run.
    failed = e.normalize(check(73, conclusion="failure", suite=100), run(10), SUBJECT, OK)
    assert codes([good, failed]) == ["EVIDENCE_CONFLICT"]
    unknown = e.normalize(check(74, suite=110), None, SUBJECT, OK)
    assert codes([good, unknown]) == ["EVIDENCE_CONFLICT"]

    # Reruns: the latest attempt of one run supersedes the earlier one.
    rerun = e.normalize(check(75, suite=70), run(attempt=2), SUBJECT, OK)
    first_failed = e.normalize(check(76, conclusion="failure", suite=70), run(), SUBJECT, OK)
    assert codes([first_failed, rerun]) == []
    # Every result of the latest attempt counts, in any order.
    same_attempt = e.normalize(check(79, conclusion="failure", suite=70), run(), SUBJECT, OK)
    assert codes([good, same_attempt]) == codes([same_attempt, good]) == ["EVIDENCE_CONFLICT"]
    assert codes([failed]) == ["EVIDENCE_FAILED:intent-gate"]
    assert codes([e.normalize(check(conclusion=None), run(), SUBJECT, OK)]) == ["EVIDENCE_PENDING:intent-gate"]

    # Requirements the delegation never declared cannot be satisfied.
    assert codes([good], ("nonexistent",)) == ["EVIDENCE_UNDECLARED:nonexistent"]

    print("evidence tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
