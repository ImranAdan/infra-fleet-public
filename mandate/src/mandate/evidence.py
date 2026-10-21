"""Evidence: GitHub Actions check results as typed facts, judged on three axes.

normalize() turns a check run and the workflow run behind it into an
EvidenceRecord that keeps the provider IDs, so a receipt can name exactly what
was relied on. evaluate() checks each record a delegation class requires on
three independent axes, and a green conclusion never shortcuts another:

- authenticity: the declared producer made it (GitHub Actions App, workflow
  path, event, and head branch for dispatches). A ruleset's source binding
  only names the App, which every workflow in the repository shares.
- applicability: it is about this subject (repository, head, base, policy).
  Genuine evidence about another subject is EVIDENCE_NOT_APPLICABLE (D-21).
- sufficiency: the class's named requirements each have one consistent,
  completed, successful result.

It returns failures, not outcomes. Outcome precedence and the public
reason-code registry belong to the decision (KAN-24); this module never
authorizes anything. PR prose is not an input, so it can satisfy nothing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from mandate.delegation import Delegation

VERSION = 1
# GitHub Actions' App ID on github.com, the source of every workflow check run.
ACTIONS_APP_ID = 15368
SUCCESS = "success"


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
    head_sha: str
    base_sha: str | None
    policy: str
    started_at: str | None
    completed_at: str | None

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


@dataclass(frozen=True)
class Evaluation:
    accepted: tuple[tuple[str, tuple[EvidenceRecord, ...]], ...]  # requirement -> records
    failures: tuple[tuple[str, str], ...]  # (code, detail)


def normalize(check_run: dict, workflow_run: dict | None, subject: Subject) -> EvidenceRecord:
    """Record one check run's facts; decides nothing.

    ``workflow_run`` is the run GitHub reports for the check's suite. If it is
    missing or belongs to another suite, the producer is unknown.
    """
    suite = (check_run.get("check_suite") or {}).get("id")
    run = (
        workflow_run
        if workflow_run and suite is not None and workflow_run.get("check_suite_id") == suite
        else {}
    )
    head = check_run["head_sha"]
    base = next(
        (pr["base"]["sha"] for pr in run.get("pull_requests") or [] if pr["head"]["sha"] == head),
        None,
    )
    app = check_run.get("app") or {}
    return EvidenceRecord(
        version=VERSION,
        check=check_run["name"],
        conclusion=check_run.get("conclusion"),
        app_id=app.get("id"),
        app_slug=app.get("slug"),
        check_run_id=check_run["id"],
        check_suite_id=suite,
        run_id=run.get("id"),
        run_attempt=run.get("run_attempt"),
        workflow=run["path"].split("@", 1)[0] if run.get("path") else None,
        event=run.get("event"),
        head_branch=run.get("head_branch"),
        repository=(run.get("repository") or {}).get("full_name"),
        head_sha=head,
        base_sha=base,
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
            # D-21: still obtainable (rerun on this subject), but say why it was refused.
            failures.append(
                (
                    f"EVIDENCE_NOT_APPLICABLE:{name}",
                    "; ".join(
                        f"{producer.check!r} check run {r.check_run_id} (run {r.run_id}) is about another "
                        f"{'/'.join(applicability(r, subject))}"
                        for r in sorted(genuine, key=lambda r: r.check_run_id)
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
