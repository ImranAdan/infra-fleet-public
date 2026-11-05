"""Evidence: GitHub Actions check results as typed facts, judged on three axes.

normalize() turns a check run and the workflow run behind it into an
EvidenceRecord that keeps the provider IDs, so a receipt can name exactly what
was relied on. evaluate() checks each record a delegation class requires on
three independent axes, and a green conclusion never shortcuts another:

- authenticity: the declared producer made it (GitHub Actions App, workflow
  path, event, and head branch for dispatches). A ruleset's source binding
  only names the App, which every workflow in the repository shares.
- applicability: it is about this subject (repository, head, base, policy).
  Genuine evidence about another subject is EVIDENCE_NOT_APPLICABLE.
- sufficiency: the class's named requirements each have one consistent,
  completed, successful result.

It returns failures, not outcomes. Outcome precedence and the public
reason-code registry belong to the decision module; this module never
authorizes anything. PR prose is not an input, so it can satisfy nothing.

The base a pull_request result is about is the one its producer compared,
proven by tested() (capture contract v1) from the provider's own records of
that job. A run's pull request association is never read: GitHub lists only
open PRs there, and it says nothing about which base a run tested. When the
capture proves nothing, the base is unknown, never filled in from the PR.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from typing import Any, NamedTuple

import yaml

from mandate.delegation import Delegation

VERSION = 2  # 2: base_sha is the captured tested base, never the PR association
# GitHub Actions' App ID on github.com, the source of every workflow check run.
ACTIONS_APP_ID = 15368
SUCCESS = "success"
CAPTURE_VERSION = 1
MERGE_REF = re.compile(r"refs/pull/\d+/merge")
# ponytail: contract v1 knows one comparing step, the Intent Gate action
# pinned to a commit, given these two inputs; another producer needs its own
# contract version.
SUPPORTED = re.compile(r"ImranAdan/infra-fleet-advisor-public/\.github/actions/intent-gate@[0-9a-f]{40}")
INPUTS = {"base-sha", "head-sha"}
# A job log line: the runner's timestamp, then the text. The runner opens an
# action step with "##[group]Run <uses>" and echoes its `with:` inputs
# before it runs.
STAMP = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z (.*)")
ECHO = re.compile(r"  (base|head)-sha: (.*)")


@dataclass(frozen=True)
class Subject:
    """What a decision is about; evidence must be about exactly this."""

    repository: str
    head_sha: str
    base_sha: str
    policy: str  # Delegation.source


@dataclass(frozen=True)
class EvidenceRecord:
    version: int
    check: str
    conclusion: str | None  # None while the check is still running
    app_id: int | None
    app_slug: str | None
    check_run_id: int
    check_suite_id: int | None
    run_id: int | None  # None: no workflow run correlates to this check
    run_attempt: int | None
    workflow: str | None
    event: str | None
    head_branch: str | None
    repository: str | None
    head_sha: str  # the check's head: the pull request head
    base_sha: str | None  # the base the producer compared; None when unproven
    compared_sha: str | None  # the merge of head into base that it compared
    unproven: str | None  # why the compared commits are unknown
    policy: str
    started_at: str | None
    completed_at: str | None

    def __post_init__(self) -> None:
        """A proof is whole or absent: a base with the merge it was compared
        in and no reason, or neither, with the reason. Nothing else can be
        built or read back, so no other shape reaches evaluate() or a receipt."""
        whole = self.base_sha is not None and self.compared_sha is not None and self.unproven is None
        if not whole and not (self.base_sha is None and self.compared_sha is None and self.unproven):
            raise ValueError(f"evidence record {self.check_run_id} has an incomplete capture proof")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRecord:
        names = {f.name for f in fields(cls)}
        if set(data) != names:
            raise ValueError(f"evidence record fields differ: {sorted(set(data) ^ names)}")
        if type(data["version"]) is not int or data["version"] != VERSION:
            raise ValueError(f"unsupported evidence record version {data['version']!r}")
        for f in fields(cls):  # annotations are not enforced at runtime: check them
            allowed = _TYPES[f.type]
            if type(data[f.name]) not in allowed:  # type(): a bool is not an int here
                raise ValueError(f"evidence record field {f.name} is {type(data[f.name]).__name__}, not {f.type}")
        return cls(**data)


_TYPES = {"int": (int,), "str": (str,), "int | None": (int, type(None)), "str | None": (str, type(None))}


class Tested(NamedTuple):
    """What tested() proved a producer compared, or why it proved nothing."""

    base_sha: str | None
    compared_sha: str | None
    unproven: str | None


@dataclass(frozen=True)
class Evaluation:
    accepted: tuple[tuple[str, tuple[EvidenceRecord, ...]], ...]  # requirement -> records
    failures: tuple[tuple[str, str], ...]  # (code, detail)


def _run(check_run: dict, workflow_run: dict | None) -> dict:
    """``workflow_run`` when it is the run of the check's suite, else {}."""
    suite = (check_run.get("check_suite") or {}).get("id")
    if workflow_run and suite is not None and workflow_run.get("check_suite_id") == suite:
        return workflow_run
    return {}


def _json(text: str | None) -> dict:
    try:
        data = json.loads(text) if text is not None else None
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _comparing(sources: list[str]) -> list[dict]:
    """The supported comparing steps in the producer's workflow sources."""
    found = []
    for text in sources:
        try:
            jobs = (yaml.safe_load(text) or {}).get("jobs") or {}
            found += [step for job in jobs.values() for step in job.get("steps") or []
                      if isinstance(step, dict) and SUPPORTED.fullmatch(str(step.get("uses")))]
        except (yaml.YAMLError, AttributeError, TypeError):
            return []
    return found


def tested(
    check_run: dict,
    workflow_run: dict | None,
    get: Callable[[str], str | None],
    read_at: Callable[[str], Callable[[str], str | None]],
) -> Tested:
    """The base and merge commit the producer of ``check_run`` compared, from
    its run's exact provider records, or why they are unknown. ``get(path)``
    is the raw text of ``repos/<repository>/<path>``, None when refused (a log
    gone after retention is HTTP 410); ``read_at(sha)(path)`` a file there.

    Capture contract v1, every step required:

    1. The Actions job with the check run's ID is that check run, in the
       run's reported attempt, on the check's head.
    2. The run records exactly one commit it ran its workflows from, a pull
       request merge ref in its own repository: the merge it checked out.
    3. That commit merges the check's head (second parent) into a base.
    4. The producer's workflows there are the base's own, so the change did
       not edit what ran.
    5. Those workflows hold exactly one supported comparing step, given both
       inputs, and the job ran that step, by its name, to success.
    6. The job log opens that step's block once ("##[group]Run <its uses>")
       and its `with:` echo names that base and merge, once each. Inputs
       echoed anywhere else, or by another action, count for nothing, and
       any extra echo makes the log ambiguous.
    """
    check_id, head = check_run["id"], check_run["head_sha"]
    run = _run(check_run, workflow_run)
    if not run:
        return Tested(None, None, f"no workflow run correlates to check run {check_id}")
    job = _json(get(f"actions/jobs/{check_id}"))
    if not job:
        return Tested(None, None, f"job {check_id} is unavailable")
    bound = (job.get("run_id"), job.get("run_attempt"), job.get("head_sha"), str(job.get("check_run_url")))
    if bound[:3] != (run.get("id"), run.get("run_attempt"), head) or not bound[3].endswith(f"/check-runs/{check_id}"):
        return Tested(None, None, f"job {check_id} is not attempt {run.get('run_attempt')} of run {run.get('id')} for this check")
    repository = (run.get("repository") or {}).get("full_name")
    refs = [w for w in run.get("referenced_workflows") or [] if isinstance(w, dict)]
    merges = {w.get("sha") for w in refs}
    if len(merges) != 1 or not all(
        MERGE_REF.fullmatch(str(w.get("ref"))) and str(w.get("path")).startswith(f"{repository}/") for w in refs
    ):
        return Tested(None, None, f"run {run.get('id')} records no single merge commit it ran from")
    merge = merges.pop()
    commit = _json(get(f"git/commits/{merge}"))
    parents = [p.get("sha") for p in commit.get("parents") or [] if isinstance(p, dict)]
    if len(parents) != 2 or parents[1] != head:
        return Tested(None, None, f"commit {merge} is not a merge of this head into a base")
    base = parents[0]
    producer = [str(run.get("path")).split("@", 1)[0]]
    producer += [str(w["path"]).removeprefix(f"{repository}/").split("@", 1)[0] for w in refs]
    sources = []
    for path in producer:
        ran = read_at(merge)(path)
        if ran is None or ran != read_at(base)(path):
            return Tested(None, None, f"producer {path} differs from its version at the tested base")
        sources.append(ran)
    steps = _comparing(sources)
    if len(steps) != 1 or not (isinstance(steps[0].get("with"), dict) and INPUTS <= set(steps[0]["with"])):
        return Tested(None, None, f"run {run.get('id')} producer has no single supported comparing step")
    uses = steps[0]["uses"]
    name = steps[0].get("name") or f"Run {uses}"
    if [s.get("conclusion") for s in job.get("steps") or [] if isinstance(s, dict) and s.get("name") == name] != ["success"]:
        return Tested(None, None, f"job {check_id} did not run its comparing step {name!r} to success")
    log = get(f"actions/jobs/{check_id}/logs")
    if log is None:
        return Tested(None, None, f"job {check_id} log is unavailable, expired or missing")
    texts = [m.group(1) for m in map(STAMP.fullmatch, log.splitlines()) if m]
    opened = [i for i, text in enumerate(texts) if text == f"##[group]Run {uses}"]
    block = texts[opened[0] + 1:] if len(opened) == 1 else []
    block = block[:block.index("##[endgroup]")] if "##[endgroup]" in block else []
    inside = sorted(m.groups() for m in map(ECHO.fullmatch, block[1:]) if m) if block[:1] == ["with:"] else []
    anywhere = sorted(m.groups() for m in map(ECHO.fullmatch, texts) if m)
    if inside != [("base", base), ("head", merge)] or anywhere != inside:
        return Tested(None, None,
                      f"job {check_id} log does not show exactly one comparison of {base}...{merge} by its comparing step")
    return Tested(base, merge, None)


def normalize(check_run: dict, workflow_run: dict | None, subject: Subject, tested: Tested) -> EvidenceRecord:
    """Record one check run's facts; decides nothing.

    ``workflow_run`` is the run GitHub reports for the check's suite. If it is
    missing or belongs to another suite, the producer is unknown. ``tested``
    is what tested() proved its producer compared.
    """
    run = _run(check_run, workflow_run)
    app = check_run.get("app") or {}
    return EvidenceRecord(
        version=VERSION,
        check=check_run["name"],
        conclusion=check_run.get("conclusion"),
        app_id=app.get("id"),
        app_slug=app.get("slug"),
        check_run_id=check_run["id"],
        check_suite_id=(check_run.get("check_suite") or {}).get("id"),
        run_id=run.get("id"),
        run_attempt=run.get("run_attempt"),
        workflow=run["path"].split("@", 1)[0] if run.get("path") else None,
        event=run.get("event"),
        head_branch=run.get("head_branch"),
        repository=(run.get("repository") or {}).get("full_name"),
        head_sha=check_run["head_sha"],
        base_sha=tested.base_sha,
        compared_sha=tested.compared_sha,
        unproven=tested.unproven,
        policy=subject.policy,
        started_at=check_run.get("started_at"),
        completed_at=check_run.get("completed_at"),
    )


def authenticity(record: EvidenceRecord, producer: Any) -> tuple[str, ...]:
    """Which producer bindings fail; empty means the declared producer made it."""
    failed = []
    if record.app_id != ACTIONS_APP_ID:
        failed.append("APP")
    if record.workflow != producer.workflow:
        failed.append("WORKFLOW")
    if record.event != producer.event:
        failed.append("EVENT")
    if producer.head_branch is not None and record.head_branch != producer.head_branch:
        failed.append("HEAD_BRANCH")
    return tuple(failed)


def applicability(record: EvidenceRecord, subject: Subject) -> tuple[str, ...]:
    """Which subject bindings fail; empty means it is about this decision.

    ponytail: a workflow_dispatch run has no pull request, so its base is
    unknown and only head binding applies; dispatch producers get head_branch.
    """
    failed = []
    if record.repository != subject.repository:
        failed.append("REPOSITORY")
    if record.head_sha != subject.head_sha:
        failed.append("HEAD")
    if record.event != "workflow_dispatch" and record.base_sha != subject.base_sha:
        failed.append("BASE")
    if record.policy != subject.policy:
        failed.append("POLICY")
    return tuple(failed)


def _mismatch(check: str, record: EvidenceRecord, subject: Subject) -> str:
    """Why genuine evidence is about another subject. A base the capture
    could not prove is unknown, not a different one."""
    failed = applicability(record, subject)
    unknown = record.base_sha is None and "BASE" in failed
    known = [f for f in failed if not (unknown and f == "BASE")]
    parts = [f"is about another {'/'.join(known)}"] if known else []
    if unknown:
        parts.append(f"tested base is unknown ({record.unproven or 'not captured'})")
    run = f"{check!r} check run {record.check_run_id} (run {record.run_id})"
    return f"{run}{' ' if known else ': '}{'; '.join(parts)}"


def _latest_attempts(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """A rerun supersedes earlier attempts of the same workflow run; every
    result of the latest attempt is kept, so input order cannot matter."""
    latest: dict[int | None, int] = {}
    for record in records:
        latest[record.run_id] = max(latest.get(record.run_id, 0), record.run_attempt or 0)
    return [r for r in records if (r.run_attempt or 0) == latest[r.run_id]]


def evaluate(
    delegation: Delegation,
    require: tuple[str, ...],
    records: list[EvidenceRecord],
    subject: Subject,
) -> Evaluation:
    """Judge ``records`` against a class's ``require`` names, failing closed."""
    producers = dict(delegation.evidence)
    accepted: list[tuple[str, tuple[EvidenceRecord, ...]]] = []
    failures: list[tuple[str, str]] = []
    for name in require:
        producer = producers.get(name)
        if producer is None:
            failures.append((f"EVIDENCE_UNDECLARED:{name}", "the delegation declares no such producer"))
            continue
        named = [r for r in records if r.check == producer.check]
        # Off-subject results, genuine or not, carry no weight either way. An
        # unattributable result has no run to bind, so only its head can count.
        unknown = [r for r in named if r.run_id is None and r.head_sha == subject.head_sha]
        wrong = [
            r
            for r in named
            if r.run_id is not None and authenticity(r, producer) and not applicability(r, subject)
        ]
        for record in wrong:
            failures.append(
                (
                    "CHECK_WRONG_SOURCE",
                    f"{producer.check!r} check run {record.check_run_id} failed "
                    f"{'/'.join(authenticity(record, producer))} binding",
                )
            )
        genuine = _latest_attempts(
            [r for r in named if r.run_id is not None and not authenticity(r, producer)]
        )
        current = [r for r in genuine if not applicability(r, subject)]
        if not current and genuine:
            # Still obtainable (rerun on this subject), but say why it was refused.
            failures.append(
                (
                    f"EVIDENCE_NOT_APPLICABLE:{name}",
                    "; ".join(
                        _mismatch(producer.check, r, subject) for r in sorted(genuine, key=lambda r: r.check_run_id)
                    ),
                )
            )
            continue
        if not current:
            failures.append((f"EVIDENCE_REQUIRED:{name}", f"no current {producer.check!r} from its producer"))
            continue
        conclusions = {r.conclusion for r in current}
        if unknown or (SUCCESS in conclusions and len(conclusions - {None}) > 1):
            failures.append(
                ("EVIDENCE_CONFLICT", f"{producer.check!r} has conflicting or unattributable results")
            )
        elif None in conclusions:
            failures.append((f"EVIDENCE_PENDING:{name}", f"{producer.check!r} is still running"))
        elif conclusions != {SUCCESS}:
            failures.append((f"EVIDENCE_FAILED:{name}", f"{producer.check!r} concluded {sorted(conclusions)}"))
        elif not wrong:
            accepted.append((name, tuple(sorted(current, key=lambda r: r.check_run_id))))
    return Evaluation(accepted=tuple(accepted), failures=tuple(failures))
