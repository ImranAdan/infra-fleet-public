"""Owner delegation: what Mandate may authorize in one repository, and what escalates.

A delegation is a TOML file in the owner-only repository
ImranAdan/mandate-delegation, at repositories/<repository-name>.toml. Mandate
reads it at an immutable commit, so the decision it records names exactly the
rules it applied. The loader is strict: an unknown key, a bad value, or a
class that tries to authorize a reserved category makes the whole file
invalid (DELEGATION_INVALID), and an invalid delegation authorizes nothing.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

DELEGATION_REPOSITORY = "ImranAdan/mandate-delegation"

# Categories the engine reports (mandate.gate), the ones the contract adds, and
# the reserved surfaces reserved_findings() reports by path.
CATEGORIES = frozenset(
    {
        "admission-policy",
        "agent-instructions",
        "credential",
        "decision-record",
        "delegation",
        "dependency",
        "dependency-manifest",
        "enforcement",
        "evidence-producer",
        "iam",
        "intent-policy",
        "merge-authority",
        "migration",
        "permanent-infrastructure",
        "permission-added",
        "permission-removed",
        "product-requirements",
        "workflow",
    }
)
# Never delegable in version 1: these change who may act or what judges merges.
# Operational admission-policy is delegable; constitutional intent-policy is not.
RESERVED = frozenset(
    {
        "agent-instructions",
        "credential",
        "delegation",
        "enforcement",
        "evidence-producer",
        "iam",
        "intent-policy",
        "merge-authority",
        "migration",
        "permanent-infrastructure",
        "permission-added",
    }
)
# Reserved surfaces found by path alone, so no owner class and no class order can
# reach them: each reports a RESERVED category, which parse() never lets a class
# authorize. Evidence producers are added per delegation in reserved_findings().
RESERVED_PATHS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("intent-policy", re.compile(r"^intent/"), "declared intent changed"),
    ("enforcement", re.compile(r"^\.github/rulesets/|(?:^|/)[^/]*ruleset[^/]*\.json$"), "ruleset changed"),
    ("enforcement", re.compile(r"(?:^|/)CODEOWNERS$"), "code owners changed"),
    ("enforcement", re.compile(r"^mandate/"), "decision engine changed"),
    ("agent-instructions", re.compile(r"(?:^|/)(?:AGENTS|CLAUDE)\.md$"), "agent instructions changed"),
)
MATCH_KEYS = frozenset(
    {
        "category",
        "paths",
        "author",
        "update",
        "signed",
        "lockfile_sibling",
        "permission_delta",
        "secret_delta",
        "trigger_delta",
    }
)
RECOVERY = ("R0", "R1", "R2", "R3", "R4")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class DelegationError(ValueError):
    """The delegation cannot be used. ``code`` is the decision reason code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class Evidence:
    check: str
    workflow: str
    event: str
    head_branch: str | None = None


@dataclass(frozen=True)
class DelegationClass:
    id: str
    categories: tuple[str, ...]
    decide: str
    require: tuple[str, ...]
    recovery: str | None
    match: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class Delegation:
    repository: str
    mode: str
    owner: str
    agents: tuple[str, ...]
    evidence: tuple[tuple[str, Evidence], ...]
    classes: tuple[DelegationClass, ...]
    source: str  # "<delegation repo>@<commit>:<path>", recorded in every receipt

    @property
    def identity_collision(self) -> bool:
        """An agent listed under the owner's name can never clear an escalation."""
        return self.owner.casefold() in {agent.casefold() for agent in self.agents}


def _invalid(detail: str) -> DelegationError:
    return DelegationError("DELEGATION_INVALID", detail)


def _keys(table: Any, allowed: frozenset[str], required: frozenset[str], where: str) -> None:
    if not isinstance(table, dict):
        raise _invalid(f"{where} must be a table")
    unknown = set(table) - allowed
    if unknown:
        raise _invalid(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
    missing = required - set(table)
    if missing:
        raise _invalid(f"{where} is missing: {', '.join(sorted(missing))}")


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{where} must be a non-empty string")
    return value


def parse(text: str, repository: str, source: str) -> Delegation:
    """Validate one delegation file for ``repository``, failing closed."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _invalid(f"not valid TOML: {exc}") from exc
    top = frozenset({"version", "repository", "mode", "owner", "agents", "evidence", "classes"})
    _keys(data, top, top, "delegation")
    if data["version"] != 1:
        raise _invalid(f"unsupported version {data['version']!r}")
    if data["repository"] != repository:
        raise _invalid(f"file is for {data['repository']!r}, not {repository!r}")
    if data["mode"] not in ("shadow", "enforce"):
        raise _invalid("mode must be 'shadow' or 'enforce'")
    owner = _text(data["owner"], "owner")
    agents = data["agents"]
    if not isinstance(agents, list):
        raise _invalid("agents must be a list")
    agents = tuple(_text(agent, "agents[]") for agent in agents)

    evidence: dict[str, Evidence] = {}
    if not isinstance(data["evidence"], dict) or not data["evidence"]:
        raise _invalid("evidence must declare at least one producer")
    for name, spec in data["evidence"].items():
        where = f"evidence.{name}"
        if not NAME.match(name):
            raise _invalid(f"{where}: names are lowercase words joined by hyphens")
        _keys(
            spec,
            frozenset({"check", "workflow", "event", "head_branch"}),
            frozenset({"check", "workflow", "event"}),
            where,
        )
        if not _text(spec["workflow"], f"{where}.workflow").startswith(".github/workflows/"):
            raise _invalid(f"{where}.workflow must be under .github/workflows/")
        if spec["event"] not in ("pull_request", "workflow_dispatch"):
            raise _invalid(f"{where}.event must be pull_request or workflow_dispatch")
        if "head_branch" in spec and spec["event"] != "workflow_dispatch":
            raise _invalid(f"{where}.head_branch is only valid for workflow_dispatch")
        if any(spec["check"] == other.check for other in evidence.values()):
            raise _invalid(f"{where}: another producer already claims the same check {spec['check']!r}")
        evidence[name] = Evidence(
            check=_text(spec["check"], f"{where}.check"),
            workflow=spec["workflow"],
            event=spec["event"],
            head_branch=spec.get("head_branch"),
        )

    classes: list[DelegationClass] = []
    if not isinstance(data["classes"], list) or not data["classes"]:
        raise _invalid("classes must be a non-empty list")
    seen: set[str] = set()
    for index, raw in enumerate(data["classes"]):
        where = f"classes[{index}]"
        _keys(
            raw,
            frozenset({"id", "match", "decide", "require", "recovery"}),
            frozenset({"id", "match", "decide"}),
            where,
        )
        class_id = _text(raw["id"], f"{where}.id")
        if not NAME.match(class_id) or class_id in seen:
            raise _invalid(f"{where}.id must be a unique lowercase hyphenated name")
        seen.add(class_id)
        where = f"class {class_id}"
        _keys(raw["match"], MATCH_KEYS, frozenset({"category"}), f"{where}.match")
        category = raw["match"]["category"]
        categories = (category,) if isinstance(category, str) else category
        if not isinstance(categories, (list, tuple)) or not categories:
            raise _invalid(f"{where}.match.category must be a category or a list of them")
        unknown = [c for c in categories if c not in CATEGORIES]
        if unknown:
            raise _invalid(f"{where} names unknown categories: {', '.join(map(str, unknown))}")
        patterns = raw["match"].get("paths", [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise _invalid(f"{where}.match.paths must be a list of regular expressions")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise _invalid(f"{where}.match.paths has an invalid pattern {pattern!r}: {exc}") from None
        if raw["decide"] not in ("authorize", "escalate"):
            raise _invalid(f"{where}.decide must be 'authorize' or 'escalate'")
        reserved = RESERVED.intersection(categories)
        if raw["decide"] == "authorize" and reserved:
            raise _invalid(f"{where} tries to authorize reserved: {', '.join(sorted(reserved))}")
        require = raw.get("require", [])
        if not isinstance(require, list) or any(name not in evidence for name in require):
            raise _invalid(f"{where}.require may only name declared evidence")
        if raw["decide"] == "authorize" and not require:
            raise _invalid(f"{where} authorizes without requiring any evidence")
        recovery = raw.get("recovery")
        if recovery is not None and recovery not in RECOVERY:
            raise _invalid(f"{where}.recovery must be one of {', '.join(RECOVERY)}")
        classes.append(
            DelegationClass(
                id=class_id,
                categories=tuple(categories),
                decide=raw["decide"],
                require=tuple(require),
                recovery=recovery,
                match=tuple(sorted((k, v) for k, v in raw["match"].items() if k != "category")),
            )
        )

    delegation = Delegation(
        repository=repository,
        mode=data["mode"],
        owner=owner,
        agents=agents,
        evidence=tuple(sorted(evidence.items())),
        classes=tuple(classes),
        source=source,
    )
    if delegation.mode == "enforce" and delegation.identity_collision:
        raise DelegationError("IDENTITY_COLLISION", "the owner is also listed as an agent")
    return delegation


def path_for(repository: str) -> str:
    """Where the delegation for ``owner/name`` lives in the delegation repository."""
    return f"repositories/{repository.split('/', 1)[1]}.toml"


def fetch(repository: str, commit: str, delegation_repository: str = DELEGATION_REPOSITORY) -> Delegation:
    """Read and validate ``repository``'s delegation at one immutable commit."""
    if not COMMIT_SHA.match(commit):
        raise _invalid(f"delegation must be pinned to a full commit SHA, not {commit!r}")
    path = path_for(repository)
    try:
        text = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "gh",
                "api",
                "-H",
                "Accept: application/vnd.github.raw+json",
                f"repos/{delegation_repository}/contents/{path}?ref={commit}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise _invalid(f"cannot read {delegation_repository}@{commit}:{path}") from exc
    return parse(text, repository, f"{delegation_repository}@{commit}:{path}")


LOCAL_USES = re.compile(r"""uses:\s*['"]?\./([^\s'"@#]+)""")
# Repository scripts a workflow or script runs, by relative path. Over-matching
# only reserves more. ponytail: language-level imports (python `import x`) are
# not followed; reserve the package directory in the delegation if one matters.
SCRIPT = re.compile(r"\.(?:py|sh|bash|js|mjs|cjs|ts|rb|pl|ps1)$")
SCRIPT_REF = re.compile(r"""(?:^|(?<=[\s'"=(\[,]))((?:\./)?(?:[\w.-]+/)*[\w.-]+\.(?:py|sh|bash|js|mjs|cjs|ts|rb|pl|ps1))\b""", re.M)


def _producer_paths(delegation: Delegation, read: Callable[[str], str | None]) -> set[str]:
    """Each evidence workflow plus every local workflow, action or script it calls, transitively.

    ``read`` returns a file's text at the trusted base revision, or None. A PR
    that adds a new call must edit a producer already in this set, so reading
    the base is enough. Local actions are reserved as whole directories.
    """
    found: set[str] = set()
    pending = [spec.workflow for _, spec in delegation.evidence]
    while pending:
        path = pending.pop().rstrip("/")
        if path in found:
            continue
        found.add(path)
        if path.endswith((".yml", ".yaml")) or SCRIPT.search(path):
            texts = [read(path)]
        else:
            texts = [read(f"{path}/action.yml"), read(f"{path}/action.yaml")]
        for text in texts:
            pending.extend(LOCAL_USES.findall(text or ""))
            pending.extend(m.removeprefix("./") for m in SCRIPT_REF.findall(text or ""))
    return found


def reserved_findings(
    delegation: Delegation, paths: list[str], read: Callable[[str], str | None]
) -> list[tuple[str, str]]:
    """Reserved (category, description) findings for changed ``paths``; each escalates."""
    producers = _producer_paths(delegation, read)
    findings = []
    for path in paths:
        if any(path == p or path.startswith(f"{p}/") for p in producers):
            findings.append(("evidence-producer", f"evidence producer changed: {path}"))
        findings.extend(
            (category, f"{description}: {path}")
            for category, pattern, description in RESERVED_PATHS
            if pattern.search(path)
        )
    return findings


def drifted(decided: Delegation, current: Delegation) -> bool:
    """Whether the rules changed between a decision and its execution."""
    return decided.source != current.source or decided != current
