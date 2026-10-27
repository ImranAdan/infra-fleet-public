#!/usr/bin/env python3
"""Mandate decision engine: decide whether an agent-authored pull request may merge.

One implementation shared by every governed repository. A repository binds it
to its own decision policy through a thin entry point (for example
.claude/skills/merge-gate/merge_ready.py), which calls cli() with the policy
path and the repository's self-test.

Exit codes:
  0  READY    all mechanical and decision checks hold
  1  BLOCKED  evidence, CI, review, mergeability, or a judge rejection blocks it
 10  PARK     an owner-only category needs current-head owner approval
 11  JUDGE    an independent judge decision for this head commit is missing
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.parse
from pathlib import Path
from typing import Any, Callable

Finding = tuple[str, str]

GREEN = {"success", "skipped", "neutral"}
PLACEHOLDER = re.compile(r"`command`\s*(→|->)\s*result", re.I)

COMMON_PATH_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "workflow",
        re.compile(r"^\.github/(?:workflows|actions)/"),
        "automation code changed",
    ),
    ("intent-policy", re.compile(r"^intent/"), "declared intent changed"),
    ("intent-policy", re.compile(r"^policy\.yaml$"), "advisor policy changed"),
    ("admission-policy", re.compile(r"^policies/"), "admission policy changed"),
    ("admission-policy", re.compile(r"^k8s/.*/policies/"), "cluster admission policy changed"),
    ("decision-record", re.compile(r"^docs/(?:decisions|pdr)/"), "decision record changed"),
    ("decision-record", re.compile(r"^docs/[^/]*-DDR\.md$"), "decision record changed"),
    (
        "product-requirements",
        re.compile(r"^docs/product-requirements\.md$"),
        "product requirements changed",
    ),
    (
        "permanent-infrastructure",
        re.compile(r"^infrastructure/permanent/"),
        "permanent infrastructure changed",
    ),
    (
        "migration",
        re.compile(
            r"(?:^|/)(?:migrations?|alembic/versions|db/(?:migrate|migrations))(?:/|$)|"
            r"(?:^|/)schema\.(?:sql|prisma)$",
            re.I,
        ),
        "state, schema or data migration changed",
    ),
    (
        "dependency-manifest",
        re.compile(
            r"(^|/)(?:pyproject\.toml|uv\.lock|requirements[^/]*\.txt|"
            r"package(?:-lock)?\.json|go\.(?:mod|sum))$"
        ),
        "dependency manifest changed",
    ),
    (
        "iam",
        re.compile(r"^infrastructure/.*/(?:iam|[^/]*[-_]iam)\.tf$"),
        "IAM definition changed",
    ),
    (
        "permission-added",
        re.compile(r"(?:^|/)(?:rbac|clusterrole|rolebinding|role)[^/]*\.ya?ml$", re.I),
        "Kubernetes RBAC file changed",
    ),
)

# Which paths are merge authority is decided per repository by its decision
# policy and installed with configure(). Until then every path counts as merge
# authority, so an unconfigured engine fails closed (PARK).
PATH_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("merge-authority", re.compile(""), "merge authority changed"),
    *COMMON_PATH_RULES,
)
# Verified Dependabot version-only bumps are opt-in per repository.
DEPENDABOT_VERSION_ONLY = False

WORKFLOW = re.compile(r"^\.github/(?:workflows|actions)/.+\.ya?ml$")
AUTOMATION = re.compile(r"^\.github/(?:workflows|actions)/")
# A diff line cannot follow YAML: an anchor, alias, tag, merge key, block
# scalar or explicit key can each carry a permission value off its key's line.
# So any workflow line with a bare write, a permissions key or an alias (any
# anchor name YAML allows) counts.
PERMISSION = re.compile(
    r"""(?:^|[\s{,])['"]?permissions['"]?\s*:|\bwrite\b|(?:^|[:,\[{]\s*|-\s+)\*[^\s,\[\]{}]"""
)
# A double-quoted scalar decodes escapes ("wri\x74e" is write), and one left
# open continues on the next line, as does an explicit tag's value: what such
# a line means is not on it, so it counts as a permission change too.
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")
TAG = re.compile(r"(?:^|:\s+|-\s+|(?<![${])[\[{,]\s*)!\S")


def _decoded(text: str) -> str:
    """The line with each double-quoted scalar's escapes decoded."""
    return QUOTED.sub(
        lambda m: ESCAPE.sub(
            lambda e: chr(min(int(e.group(1)[1:], 16), 0x10FFFF)) if len(e.group(1)) > 1 else e.group(1),
            m.group(0),
        ),
        text,
    )


def _unseen_value(text: str) -> bool:
    """An open double-quoted scalar or an explicit tag: the value is elsewhere."""
    rest = re.sub(r"'(?:[^']|'')*'", "", QUOTED.sub("", text))
    return '"' in rest or bool(TAG.search(text))
# Any line naming the secrets context, in any case: toJSON(secrets), an
# operand after ||, or an expression split across lines all name it.
SECRETS = re.compile(r"\bsecrets\b", re.I)
RBAC_FILE = re.compile(r"(?:^|/)(?:rbac|clusterrole|rolebinding|role)[^/]*\.ya?ml$", re.I)
DOCKERFILE = re.compile(r"(^|/)Dockerfile[^/]*$")
YAML = re.compile(r"\.ya?ml$")
TERRAFORM = re.compile(r"\.tf$")
PRIVILEGED_TRIGGER = re.compile(r"\b(?:pull_request_target|issue_comment|workflow_run)\b")


def _finding(category: str, description: str) -> Finding:
    return category, description


def _adds_privileged_trigger(text: str) -> bool:
    """Recognize mapping, scalar, list and flow-map GitHub event syntax."""
    if re.match(
        r"(?:-\s*)?['\"]?(?:pull_request_target|issue_comment|workflow_run)"
        r"['\"]?\s*(?::|$)",
        text,
    ):
        return True
    if not re.match(r"['\"]?on['\"]?\s*:", text):
        return False
    return bool(PRIVILEGED_TRIGGER.search(text))


def _adds_remote_action(text: str) -> bool:
    """Return whether an added uses value points outside this repository."""
    match = re.match(r"(?:-\s*)?uses:\s+(\S+)", text)
    if not match:
        return False
    target = match.group(1).strip("'\"")
    return not target.startswith(("./", "/", "$/"))


def _remote_action_is_pinned(text: str) -> bool:
    """Require remote GitHub actions at a commit and container actions at a fixed image."""
    match = re.match(r"(?:-\s*)?uses:\s+(\S+)", text)
    if not match:
        return True
    target = match.group(1).strip("'\"")
    if not _adds_remote_action(text):
        return True
    if target.startswith("docker://"):
        return _container_ref_is_pinned(target.removeprefix("docker://"))
    _, separator, ref = target.rpartition("@")
    return bool(separator and re.fullmatch(r"[0-9a-f]{40}", ref))


def _container_ref_is_pinned(reference: str) -> bool:
    """Accept an immutable digest or an explicit non-latest image tag."""
    if reference == "scratch":
        return True
    if re.search(r"@sha256:[0-9a-f]{64}\Z", reference):
        return True
    final = reference.rsplit("/", 1)[-1]
    if ":" not in final:
        return False
    tag = final.rsplit(":", 1)[1]
    return bool(tag and tag.casefold() != "latest" and not re.search(r"[$*?{}]", tag))


def _docker_base_is_pinned(text: str) -> bool:
    """Validate the image token in a Dockerfile FROM instruction."""
    parts = text.split()
    if not parts or parts[0].upper() != "FROM":
        return True
    images = [part for part in parts[1:] if not part.startswith("--")]
    return bool(images and _container_ref_is_pinned(images[0]))


def _stage_references(dockerfile: str) -> set[str]:
    """FROM lines naming a stage declared earlier in the same Dockerfile.

    Docker resolves such a name to that stage, not to a registry image, so
    there is nothing to pin. A name declared only later is still an image.
    """
    stages: set[str] = set()
    references: set[str] = set()
    images: set[str] = set()
    for line in dockerfile.splitlines():
        text = line.strip()
        parts = [part for part in text.split() if not part.startswith("--")]
        if len(parts) < 2 or parts[0].upper() != "FROM":
            continue
        if parts[1].casefold() in stages:
            references.add(text)
        else:
            images.add(text)
        if len(parts) >= 4 and parts[2].upper() == "AS":
            stages.add(parts[3].casefold())
    # The diff gives line text, not position: excuse a line only if every
    # occurrence of that text is a stage reference.
    return references - images


def _head_stage_references(repo: str, sha: str, diff: str) -> dict[str, set[str]]:
    """_stage_references() of every changed Dockerfile at the checked head."""
    references: dict[str, set[str]] = {}
    for path in _changed_paths(diff):
        if not DOCKERFILE.search(path):
            continue
        try:
            content = gh(
                "api",
                f"repos/{repo}/contents/{urllib.parse.quote(path)}?ref={sha}",
                "-H",
                "Accept: application/vnd.github.raw",
            )
        except subprocess.CalledProcessError:
            continue  # deleted or unreadable: no stage names, so nothing is excused
        references[path] = _stage_references(content)
    return references


def _changed_paths(diff: str) -> set[str]:
    return {
        match.group(2)
        for line in diff.splitlines()
        if (match := re.match(r"^diff --git a/(.*) b/(.*)$", line))
    }


def evidence_policy_failures(
    diff: str, stage_references: dict[str, set[str]] | None = None
) -> list[str]:
    """Reject dependency changes whose policy conditions CI cannot infer.

    stage_references maps a Dockerfile path to _stage_references() of its head
    content, so `FROM <earlier stage>` is not mistaken for an unpinned image.
    """
    stage_references = stage_references or {}
    failures: list[str] = []
    path = ""
    for line in diff.splitlines():
        header = re.match(r"^diff --git a/(.*) b/(.*)$", line)
        if header:
            path = header.group(2)
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        text = line[1:].strip()
        if (
            WORKFLOW.search(path)
            and _adds_remote_action(text)
            and not _remote_action_is_pinned(text)
        ):
            failures.append(
                f"remote action is not pinned to a full commit SHA: {path}: {text[:80]}"
            )
        if (
            DOCKERFILE.search(path)
            and re.match(r"FROM\s", text, re.I)
            and not _docker_base_is_pinned(text)
            and text not in stage_references.get(path, set())
        ):
            failures.append(
                f"container base is not pinned to a fixed tag or digest: {path}: {text[:80]}"
            )
        if (
            re.search(r"(?:^|/)requirements[^/]*\.txt$", path)
            and text
            and not text.startswith(("#", "-r ", "--requirement ", "-c ", "--constraint "))
        ):
            requirement = text.split(";", 1)[0].strip()
            if "==" not in requirement:
                failures.append(f"Python requirement is not exactly pinned: {path}: {text[:80]}")

    changed = _changed_paths(diff)
    lock_pairs = (
        ("pyproject.toml", "uv.lock"),
        ("package.json", "package-lock.json"),
        ("go.mod", "go.sum"),
    )
    for manifest, lockfile in lock_pairs:
        for path in changed:
            if path.rsplit("/", 1)[-1] != manifest:
                continue
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            expected = f"{parent}/{lockfile}" if parent else lockfile
            if expected not in changed:
                failures.append(
                    f"dependency manifest changed without its resolved lockfile: {expected}"
                )
    return list(dict.fromkeys(failures))


def _hunk_has_rbac_marker(lines: list[str], start: int) -> bool:
    """Report whether this unified-diff hunk contains unambiguous RBAC structure."""
    marker = re.compile(
        r"(?:kind:\s*(?:Cluster)?Role(?:Binding)?\b|"
        r"(?:verbs|apiGroups|resourceNames|nonResourceURLs|subjects|roleRef):)"
    )
    for candidate in lines[start + 1 :]:
        if candidate.startswith(("@@", "diff --git ")):
            break
        content = (
            candidate[1:].strip() if candidate.startswith((" ", "+", "-")) else candidate.strip()
        )
        if marker.match(content):
            return True
    return False


def _hunk_has_terraform_migration(lines: list[str], start: int) -> bool:
    """Report whether this diff hunk contains a Terraform state-migration block."""
    for candidate in lines[start + 1 :]:
        if candidate.startswith(("@@", "diff --git ")):
            break
        content = candidate[1:].strip() if candidate.startswith((" ", "+", "-")) else ""
        if re.match(r"(?:moved|import|removed)\s*\{", content):
            return True
    return False


def _path_findings(path: str) -> list[Finding]:
    return [
        _finding(category, f"{description}: {path}")
        for category, pattern, description in PATH_RULES
        if pattern.search(path)
    ]


def _line_findings(path: str, line: str) -> list[Finding]:
    """Decision findings for one changed hunk line."""
    if not line.startswith(("+", "-")):
        return []
    added = line.startswith("+")
    text = line[1:].strip()
    verb = "adds" if added else "removes"
    findings: list[Finding] = []

    if WORKFLOW.search(path):
        # A comment line sets nothing, but GitHub evaluates ${{ }} anywhere,
        # even in a script's comment.
        comment = text.startswith("#") and "${{" not in text
        if not comment and (
            PERMISSION.search(text) or PERMISSION.search(_decoded(text)) or _unseen_value(text)
        ):
            category = "permission-added" if added else "permission-removed"
            findings.append(
                _finding(category, f"{verb} a workflow permission in {path}: {text[:80]}")
            )
        if added and _adds_privileged_trigger(text):
            findings.append(
                _finding(
                    "merge-authority", f"adds a privileged workflow trigger in {path}: {text[:80]}"
                )
            )
        if added and re.search(
            r"(?:gh\s+pr\s+merge|mergePullRequest|owner-approved|merge-gate-judge)", text
        ):
            findings.append(
                _finding("merge-authority", f"adds merge-control logic in {path}: {text[:80]}")
            )
        if added and not comment and SECRETS.search(text):
            findings.append(
                _finding("credential", f"adds a credential reference in {path}: {text[:80]}")
            )
        if added and _adds_remote_action(text):
            findings.append(_finding("dependency", f"adds a remote action in {path}: {text[:80]}"))

    if added and DOCKERFILE.search(path) and re.match(r"FROM\s", text):
        findings.append(_finding("dependency", f"adds a base image in {path}: {text[:80]}"))
    if added and YAML.search(path) and re.match(r"version:\s*['\"]?v?\d", text):
        findings.append(_finding("dependency", f"adds a chart version in {path}: {text[:80]}"))

    if TERRAFORM.search(path) and re.search(
        r"aws_iam_|\biam:[A-Za-z*]|['\"][a-z0-9-]+:[A-Za-z*]|"
        r"\b(?:actions|resources)\s*=|['\"]Resource['\"]\s*:",
        text,
        re.I,
    ):
        findings.append(_finding("iam", f"{verb} IAM configuration in {path}: {text[:80]}"))

    if TERRAFORM.search(path) and re.match(r"(?:moved|import|removed)\s*\{", text):
        findings.append(_finding("migration", f"{verb} a Terraform state migration in {path}"))

    if YAML.search(path) and re.match(
        r"(?:kind:\s*(?:Cluster)?Role(?:Binding)?\b|verbs:|apiGroups:|roleRef:|subjects:)", text
    ):
        category = "permission-added" if added else "permission-removed"
        findings.append(_finding(category, f"{verb} Kubernetes RBAC in {path}: {text[:80]}"))

    return findings


# Only top-level workflow files run; their parsed versions decide what changed.
WORKFLOW_FILE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
PRIVILEGED_EVENTS = frozenset({"pull_request_target", "issue_comment", "workflow_run"})
LEVELS = {"none": 0, "read": 1, "write": 2}
_ABSENT = object()


def strict_loader() -> Any:
    """A YAML SafeLoader whose duplicate and merge keys raise: what they mean
    depends on the parser, and GitHub does not resolve merge keys."""
    import yaml

    class Strict(yaml.SafeLoader):
        def construct_mapping(self, node: Any, deep: bool = False) -> Any:
            # A merge key (<<) has no constructor here, so building it raises.
            keys = [repr(self.construct_object(k, deep=True)) for k, _ in node.value]
            if len(keys) != len(set(keys)):
                raise ValueError("duplicate key")
            return super().construct_mapping(node, deep)

    return Strict


def read_at(repo: str, ref: str) -> Callable[[str], str | None]:
    """A file's text at one commit; None when it cannot be read."""

    def read(path: str) -> str | None:
        try:
            return gh("api", "-H", "Accept: application/vnd.github.raw+json",
                      f"repos/{repo}/contents/{urllib.parse.quote(path)}?ref={ref}")
        except subprocess.CalledProcessError:
            return None

    return read


def _level(value: Any, scope: str, side: str) -> int:
    """A permissions value's level for one scope. Absent is the repository
    default, which may grant write; an unknown value counts as least before
    and most after."""
    if value is _ABSENT:
        return 2
    if value in ("read-all", "write-all"):
        return 1 if value == "read-all" else 2
    if isinstance(value, dict) and all(isinstance(v, str) and v in LEVELS for v in value.values()):
        return LEVELS[value.get(scope, "none")]
    return 0 if side == "base" else 2


def _jobs(doc: dict[str, Any]) -> tuple[Any, dict[Any, Any]]:
    top = doc.get("permissions", _ABSENT)
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    return top, {k: v.get("permissions", top) if isinstance(v, dict) else None for k, v in jobs.items()}


def _secret_reads(doc: Any) -> dict[str, int]:
    """Each string holding an expression that names the secrets context, and each inherit."""
    found: dict[str, int] = {}
    stack = [doc]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("secrets") == "inherit":
                found["secrets: inherit"] = found.get("secrets: inherit", 0) + 1
            stack += [*item.keys(), *item.values()]
        elif isinstance(item, list):
            stack += item
        elif isinstance(item, str) and "${{" in item and re.search(r"\bsecrets\b", item, re.I):
            key = " ".join(item.split())
            found[key] = found.get(key, 0) + 1
    return found


def _events(doc: dict[str, Any]) -> set[str] | None:
    """Trigger names, or None when they cannot be read. YAML 1.1 reads on as True."""
    on = doc.get("on", doc.get(True))
    if on is None or isinstance(on, str):
        return {on} if on else set()
    if isinstance(on, (list, dict)):
        return {e for e in on if isinstance(e, str)}
    return None


def workflow_findings(path: str, base: str | None, head: str) -> list[Finding]:
    """What one workflow's head version grants beyond its base, read from the
    parsed YAML, so no spelling, alias, escape or line break can hide it. A
    head that cannot be parsed counts as a permission change; ``base`` None is
    a new workflow."""
    try:  # a missing parser (ImportError) fails closed here too
        new = yaml_load(head)
        if not isinstance(new, dict):
            raise ValueError("not a mapping")
    except Exception as exc:  # noqa: BLE001 - any parser failure: the effect is unknown
        return [_finding("permission-added", f"cannot parse {path}: {type(exc).__name__}")]
    try:
        old = {"permissions": {}} if base is None else yaml_load(base)
    except Exception:  # noqa: BLE001 - an unreadable base grants nothing to compare with
        old = None
    if not isinstance(old, dict):
        old = {"permissions": {}}
    findings: list[Finding] = []
    old_top, old_jobs = _jobs(old)
    new_top, new_jobs = _jobs(new)
    values = [old_top, new_top, *old_jobs.values(), *new_jobs.values()]
    scopes = {"*", *(k for v in values if isinstance(v, dict) for k in v if isinstance(k, str))}
    compared = new_jobs or {"(workflow)": new_top}
    widened = sorted(
        str(job) for job, value in compared.items()
        if any(_level(value, s, "head") > _level(old_jobs.get(job, old_top), s, "base") for s in scopes)
    )
    if widened:
        findings.append(_finding("permission-added", f"widens workflow permissions in {path}: {', '.join(widened)}"))
    before = _secret_reads(old)
    if any(n > before.get(k, 0) for k, n in _secret_reads(new).items()):
        findings.append(_finding("credential", f"reads more secrets in {path}"))
    events, prior = _events(new), _events(old) or set()
    if events is None or (events - prior) & PRIVILEGED_EVENTS:
        findings.append(_finding("merge-authority", f"adds a privileged workflow trigger in {path}"))
    return findings


def yaml_load(text: str) -> Any:
    import yaml

    return yaml.load(text, Loader=strict_loader())  # noqa: S506 (SafeLoader subclass)


def workflow_changes(
    diff: str, read_base: Callable[[str], str | None], read_head: Callable[[str], str | None]
) -> list[Finding]:
    """workflow_findings() for each workflow file the diff adds, changes or
    moves in; a version that cannot be read counts as a permission change."""
    found: list[Finding] = []
    for chunk in re.split(r"(?m)^(?=diff --git )", diff):
        header = re.match(r"diff --git a/(.*) b/(.*)$", chunk, re.M)
        if not header or not WORKFLOW_FILE.search(header.group(2)):
            continue
        if re.search(r"(?m)^deleted file mode ", chunk):
            continue  # a removed workflow grants nothing
        old, new = header.groups()
        added = bool(re.search(r"(?m)^new file mode ", chunk)) or not WORKFLOW_FILE.search(old)
        base = None if added else read_base(old)
        head = read_head(new)
        if head is None or (base is None and not added):
            found.append(_finding("permission-added", f"cannot read {new} at both base and head"))
            continue
        found += workflow_findings(new, base, head)
    return list(dict.fromkeys(found))


def scope_findings(diff: str) -> list[Finding]:
    """Return structured decision findings from a unified diff."""
    findings: list[Finding] = []
    path = ""
    in_hunk = False
    rbac_indent: int | None = None
    rbac_key = ""
    lines = diff.splitlines()
    hunk_start = 0
    for index, line in enumerate(lines):
        header = re.match(r"^diff --git a/(.*) b/(.*)$", line)
        if header:
            in_hunk = False
            rbac_indent = None
            rbac_key = ""
            old, path = header.group(1), header.group(2)
            for changed in dict.fromkeys((old, path)):
                findings.extend(_path_findings(changed))
            if AUTOMATION.search(path) and not AUTOMATION.search(old):
                # A rename shows only changed lines, so the moved file's
                # triggers and permissions are unseen.
                findings.append(_finding("merge-authority", f"moves {old} into automation unseen: {path}"))
            continue
        if not in_hunk:
            if line.startswith("rename from "):
                findings.extend(_path_findings(line[len("rename from ") :]))
            elif line.startswith("+++ b/"):
                path = line[6:]
            elif line.startswith("@@"):
                in_hunk = True
                rbac_indent = None
                rbac_key = ""
                hunk_start = index
            continue
        if line.startswith("@@"):
            rbac_indent = None
            rbac_key = ""
            hunk_start = index
            continue
        content = line[1:] if line.startswith((" ", "+", "-")) else line
        stripped = content.strip()
        indent = len(content) - len(content.lstrip())
        rbac_match = re.match(
            r"(verbs|apiGroups|resources|resourceNames|nonResourceURLs|subjects|roleRef):",
            stripped,
        )
        is_rbac_key = (
            bool(YAML.search(path))
            and bool(rbac_match)
            and (
                rbac_match.group(1) != "resources"
                or bool(RBAC_FILE.search(path))
                or _hunk_has_rbac_marker(lines, hunk_start)
            )
        )
        if is_rbac_key:
            rbac_indent = indent
            rbac_key = rbac_match.group(1) if rbac_match else ""
        elif (
            rbac_indent is not None
            and stripped
            and not stripped.startswith("-")
            and indent <= rbac_indent
        ):
            rbac_indent = None
            rbac_key = ""
        if (
            rbac_indent is not None
            and not is_rbac_key
            and line.startswith(("+", "-"))
            and (rbac_key != "resources" or stripped.startswith("-"))
        ):
            category = "permission-added" if line.startswith("+") else "permission-removed"
            verb = "adds" if line.startswith("+") else "removes"
            findings.append(
                _finding(category, f"{verb} a Kubernetes RBAC value in {path}: {stripped[:80]}")
            )
        if (
            TERRAFORM.search(path)
            and line.startswith(("+", "-"))
            and _hunk_has_terraform_migration(lines, hunk_start)
        ):
            findings.append(_finding("migration", f"changes a Terraform state migration in {path}"))
        findings.extend(_line_findings(path, line))
    return list(dict.fromkeys(findings))


def load_policy(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load rules by category and the judge settings, failing closed."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, str]] = {}
    for raw in data.get("rule", []):
        if not isinstance(raw, dict):
            raise ValueError("each policy rule must be a table")
        required = ("id", "category", "decider", "guidance")
        if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
            raise ValueError("each policy rule needs non-empty id, category, decider and guidance")
        if raw["decider"] not in {"evidence", "judge", "owner"}:
            raise ValueError(f"invalid decider for {raw['category']}: {raw['decider']}")
        if raw["category"] in rules:
            raise ValueError(f"duplicate policy category: {raw['category']}")
        rules[raw["category"]] = {key: raw[key] for key in required}
    judge = data.get("judge")
    if not isinstance(judge, dict) or any(
        not isinstance(judge.get(key), str) or not judge[key].strip()
        for key in ("trusted_author", "model")
    ):
        raise ValueError("policy needs judge.trusted_author and judge.model")
    evidence = data.get("evidence")
    required_checks = evidence.get("required_checks") if isinstance(evidence, dict) else None
    if not isinstance(required_checks, list) or not required_checks:
        raise ValueError("policy needs at least one evidence.required_checks entry")
    normalized: list[dict[str, str]] = []
    for item in required_checks:
        required_keys = {"group", "name", "workflow", "event"}
        allowed_keys = required_keys | {"head_branch"}
        if (
            not isinstance(item, dict)
            or not required_keys <= set(item) <= allowed_keys
            or any(not isinstance(item[key], str) or not item[key].strip() for key in item)
            or not item["workflow"].startswith(".github/workflows/")
            or item["event"] not in {"pull_request", "workflow_dispatch"}
            or ("head_branch" in item and item["event"] != "workflow_dispatch")
        ):
            raise ValueError(
                "each required check needs a group, name, workflow path and trusted event"
            )
        normalized.append({key: str(value) for key, value in item.items()})
    return rules, {
        "trusted_author": judge["trusted_author"],
        "model": judge["model"],
        "required_checks": tuple(normalized),
    }


def required_check_failures(
    runs: list[dict[str, Any]],
    required: tuple[dict[str, str], ...],
    workflow_runs: dict[str, dict[str, str]],
    sha: str,
) -> list[str]:
    """Require successful, current-head evidence from its declared workflow."""
    failures: list[str] = []
    groups = dict.fromkeys(spec["group"] for spec in required)
    for group in groups:
        specs = [spec for spec in required if spec["group"] == group]
        named = [(run, spec) for run in runs for spec in specs if run.get("name") == spec["name"]]
        if not named:
            names = " or ".join(spec["name"] for spec in specs)
            failures.append(f"required evidence check did not run: {names}")
            continue
        run, spec = max(named, key=lambda item: str(item[0].get("started_at", "")))
        provenance = workflow_runs.get(str(run.get("run_id", "")), {})
        workflow_path = provenance.get("path", "").split("@", 1)[0]
        trusted = (
            run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("app") == "github-actions"
            and workflow_path == spec["workflow"]
            and provenance.get("event") == spec["event"]
            and provenance.get("head_sha") == sha
            and (
                "head_branch" not in spec
                or provenance.get("head_branch") == spec["head_branch"]
            )
        )
        if not trusted:
            failures.append(
                f"required evidence check lacks trusted successful provenance: {run.get('name')}"
            )
    return failures


def latest_check_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest rerun for each check name, publisher and workflow.

    GitHub's ``filter=latest`` can still return two check suites for events that
    arrive together, such as Dependabot opening and labelling a pull request.
    A cancelled superseded suite must not block the successful replacement.
    Workflow identity is required before GitHub Actions runs may supersede one
    another. Other publishers remain unique, so a same-name check cannot hide
    another workflow or App's failure.
    """
    newest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in runs:
        workflow = str(run.get("workflow_path", ""))
        if run.get("app") == "github-actions" and workflow:
            identity = workflow
        else:
            identity = f"run:{run.get('id')}"
        key = (str(run.get("name", "")), str(run.get("app", "")), identity)
        order = (str(run.get("started_at", "")), int(run.get("id", 0)))
        previous = newest.get(key)
        previous_order = (
            (str(previous.get("started_at", "")), int(previous.get("id", 0)))
            if previous
            else ("", 0)
        )
        if order > previous_order:
            newest[key] = run
    return list(newest.values())


def is_current_autonomous_worker(run: dict[str, Any], run_id: str) -> bool:
    """Exclude only the trusted worker check that is presently running this gate."""
    return bool(
        run_id.isdigit()
        and str(run.get("run_id", "")) == run_id
        and run.get("workflow_path") == ".github/workflows/autonomous-merge.yml"
        and run.get("status") != "completed"
    )


def _actions_run_id(repo: str, details_url: object) -> str | None:
    """Extract a run id only from this repository's GitHub Actions job URL."""
    if not isinstance(details_url, str):
        return None
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(repo)}/actions/runs/([0-9]+)/job/[0-9]+",
        details_url,
        re.I,
    )
    return match.group(1) if match else None


def judge_decision(
    comments: list[dict[str, str]], sha: str, trusted_author: str
) -> tuple[str, frozenset[str]] | None:
    """Return the newest well-formed trusted decision for this exact head SHA."""
    marker = re.escape(f"<!-- merge-gate-judge sha={sha} -->")
    pattern = re.compile(
        rf"\A{marker}\nDECISION: (APPROVE|REJECT)\nRULES: ([^\n]*)",
    )
    for comment in reversed(comments):
        if comment.get("author") != trusted_author:
            continue
        match = pattern.search(comment.get("body", ""))
        if match:
            rule_ids = frozenset(item.strip() for item in match.group(2).split(",") if item.strip())
            return match.group(1), rule_ids
    return None


def owner_label_approval(
    events: list[dict[str, str]], repository_owner: str, head_checks_started: str
) -> bool:
    """Require the newest owner-approved label event to be the owner adding it
    after every check run on the current head had started.

    GitHub records label events and check-run starts with server time, so a
    push after the approval starts new checks and unbinds it. This replaces
    the trusted comment that the pull_request_target judge used to post.
    """
    if not repository_owner or not head_checks_started:
        return False
    for event in reversed(events):
        if event.get("label") != "owner-approved":
            continue
        return (
            event.get("event") == "labeled"
            and event.get("actor", "").casefold() == repository_owner.casefold()
            and event.get("created_at", "") > head_checks_started
        )
    return False


def owner_comment_approval(
    comments: list[dict[str, str]],
    repository_owner: str,
    sha: str,
    head_checks_started: str,
) -> bool:
    """Accept only the owner's exact, current-head command after checks started."""
    if not repository_owner or not head_checks_started:
        return False
    command = f"/approve {sha}"
    return any(
        comment.get("author", "").casefold() == repository_owner.casefold()
        and comment.get("body", "").strip() == command
        and comment.get("created_at", "") > head_checks_started
        for comment in comments
    )


def decide(
    findings: list[Finding],
    rules: dict[str, dict[str, str]],
    _labels: set[str],
    decision: tuple[str, frozenset[str]] | None,
    current_owner_approval: bool = False,
) -> tuple[str, list[str]]:
    """Apply the policy to findings after mechanical checks have passed."""
    categories = list(dict.fromkeys(category for category, _ in findings))
    owner_categories = [
        category
        for category in categories
        if category not in rules or rules[category]["decider"] == "owner"
    ]
    judge_rules = {
        rules[category]["id"]
        for category in categories
        if category in rules and rules[category]["decider"] == "judge"
    }

    if decision and decision[0] == "REJECT" and judge_rules.intersection(decision[1]):
        rejected = ", ".join(sorted(judge_rules.intersection(decision[1])))
        return "BLOCKED", [f"independent judge rejected rule(s): {rejected}"]
    if owner_categories and not current_owner_approval:
        return "PARK", [f"owner decision required for: {', '.join(owner_categories)}"]
    if judge_rules and (
        not decision or decision[0] != "APPROVE" or not judge_rules.issubset(decision[1])
    ):
        missing = (
            judge_rules if not decision or decision[0] != "APPROVE" else judge_rules - decision[1]
        )
        return "JUDGE", [f"independent judge approval required for: {', '.join(sorted(missing))}"]
    return "READY", []


def has_verification(body: str) -> bool:
    """A Verification section holding at least one real command and result."""
    match = re.search(r"^#{2,3}\s*Verification\b(.*?)(?=^#{1,3}\s|\Z)", body, re.S | re.M | re.I)
    if not match:
        return False
    section = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.S)
    section = PLACEHOLDER.sub("", section)
    return any(
        found.group(1).strip() not in ("", "command")
        for found in re.finditer(r"`([^`]+)`[^\n`]*?(?:→|->)\s*(\S[^\n]*)", section)
    )


DEPENDABOT_AUTHORS = {"app/dependabot", "dependabot[bot]"}
LOCKFILE = re.compile(r"(?:^|/)(?:\.terraform\.lock\.hcl|package-lock\.json|uv\.lock|go\.sum)$")
# One dependency reference per line; "key" must survive the bump unchanged, so
# a bump can move a version but cannot swap the image, action or package.
VERSION_LINES = (
    re.compile(
        r"^FROM\s+(?:--platform=\S+\s+)?(?P<key>[^\s:@]+)(?::\S+?)?(?:@sha256:[0-9a-f]{64})?"
        r"(?:\s+AS\s+\S+)?$",
        re.I,
    ),
    re.compile(r"^(?:-\s*)?uses:\s*(?P<key>[^\s@]+)@[0-9a-f]{40}(?:\s+#\s*\S+)?$"),
    re.compile(r"^(?P<key>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]*\])?)==\d[^\s;#]*(?P<comment>\s+#.*)?$"),
    re.compile(r'^"(?P<key>[@A-Za-z0-9_./-]+)":\s*"[\^~]?\d[\w.+-]*",?$'),
    re.compile(r'^(?P<key>version)\s*=\s*"[^"]+"$'),
)


def _version_key(text: str) -> str | None:
    for pattern in VERSION_LINES:
        if match := pattern.match(text.strip()):
            # An inline comment is part of the key: kept as is, never changed.
            return match.group("key") + (match.groupdict().get("comment") or "")
    return None


def dependabot_bump_failures(
    author: str, branch: str, commits: list[dict[str, Any]], diff: str
) -> list[str]:
    """Why a PR is not a Dependabot version-only bump; empty means it is.

    Such a PR proves itself through its exact-head checks, so it needs no
    hand-written Verification section and no autonomous-merge marker.
    """
    failures: list[str] = []
    if author not in DEPENDABOT_AUTHORS:
        failures.append(f"author {author} is not Dependabot")
    if not branch.startswith("dependabot/"):
        failures.append(f"branch {branch} is not a Dependabot branch")
    if not commits:
        failures.append("no commits")
    for commit in commits:
        if commit.get("author") != "dependabot[bot]" or not commit.get("verified"):
            failures.append("a commit is not a verified Dependabot commit")
        if "update-type: version-update:semver-major" in (commit.get("message") or ""):
            failures.append("a major version update")
    path = ""
    removed: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    for line in diff.splitlines():
        if header := re.match(r"^diff --git a/(.*) b/(.*)$", line):
            path = header.group(2)
            if header.group(1) != path:
                failures.append(f"renames a file: {path}")
            continue
        if re.match(r"^(?:new|deleted) file mode ", line):
            failures.append(f"adds or deletes a file: {path}")
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        if LOCKFILE.search(path):
            continue
        (added if line.startswith("+") else removed).setdefault(path, []).append(line[1:])
    for changed in sorted(set(removed) | set(added)):
        before, after = removed.get(changed, []), added.get(changed, [])
        if len(before) != len(after):
            failures.append(f"changes more than versions in {changed}")
            continue
        for old, new in zip(before, after):
            key = _version_key(old)
            if key is None or key != _version_key(new):
                failures.append(f"changes more than a version in {changed}: {new.strip()[:80]}")
    return list(dict.fromkeys(failures))


def dependabot_scope(findings: list[Finding]) -> list[Finding]:
    """A lockfile-only permanent change in a verified bump is a dependency bump."""
    return [
        _finding("dependency-manifest", description)
        if category == "permanent-infrastructure" and LOCKFILE.search(description)
        else (category, description)
        for category, description in findings
    ]


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return result.stdout


def merge_pull_request(number: str, repo: str, sha: str) -> None:
    """Merge only if GitHub still reports the exact head evaluated by this gate."""
    gh(
        "pr",
        "merge",
        number,
        "-R",
        repo,
        "--merge",
        "--match-head-commit",
        sha,
    )


def gh_json_lines(*args: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in gh(*args).splitlines() if line.strip()]


def review_threads(owner: str, name: str, number: str) -> list[dict[str, Any]]:
    query = """
    query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100, after: $endCursor) {
            pageInfo { hasNextPage endCursor }
            nodes { isResolved comments(first: 100) { nodes { author { login } } } }
          }
        }
      }
    }"""
    return gh_json_lines(
        "api",
        "graphql",
        "--paginate",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={number}",
        "-f",
        f"query={query}",
        "--jq",
        ".data.repository.pullRequest.reviewThreads.nodes[]",
    )


def main(argv: list[str], policy_path: Path) -> int:
    if not argv or not argv[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    number = argv[0]
    repo = (
        argv[argv.index("--repo") + 1]
        if "--repo" in argv
        else gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()
    )
    owner, name = repo.split("/")
    pr = json.loads(
        gh(
            "pr",
            "view",
            number,
            "-R",
            repo,
            "--json",
            "state,isDraft,mergeStateStatus,body,baseRefOid,headRefOid,headRefName,author,labels",
        )
    )
    blocked: list[str] = []
    if pr["state"] != "OPEN" or pr["isDraft"]:
        draft = " draft" if pr["isDraft"] else ""
        blocked.append(f"pull request is {pr['state'].lower()}{draft}")
    if pr["mergeStateStatus"] != "CLEAN":
        blocked.append(f"merge state is {pr['mergeStateStatus']} (conflicts, behind, or checks)")

    sha = pr["headRefOid"]
    raw_runs = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100&filter=latest",
        "--jq",
        ".check_runs[]|{id,name,status,conclusion,started_at,app:.app.slug,details_url}",
    )
    workflow_runs: dict[str, dict[str, str]] = {}
    for run in raw_runs:
        run_id = _actions_run_id(repo, run.get("details_url"))
        if not run_id:
            continue
        if run_id not in workflow_runs:
            details = json.loads(gh("api", f"repos/{repo}/actions/runs/{run_id}"))
            workflow_runs[run_id] = {
                key: str(details.get(key, ""))
                for key in ("path", "event", "head_sha", "head_branch")
            }
        run["run_id"] = run_id
        run["workflow_path"] = workflow_runs[run_id]["path"].split("@", 1)[0]
    current_worker = os.environ.get("AUTONOMOUS_MERGE_RUN_ID", "")
    runs = []
    for run in latest_check_runs(raw_runs):
        if not is_current_autonomous_worker(run, current_worker):
            runs.append(run)
    latest: dict[str, str] = {}
    for status in gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/commits/{sha}/statuses?per_page=100",
        "--jq",
        ".[]|{context,state}",
    ):
        latest.setdefault(status["context"], status["state"])
    pending = [run["name"] for run in runs if run["status"] != "completed"]
    pending += [context for context, state in latest.items() if state == "pending"]
    failed = [
        run["name"]
        for run in runs
        if run["status"] == "completed" and run["conclusion"] not in GREEN
    ]
    failed += [context for context, state in latest.items() if state in ("failure", "error")]
    if not runs and not latest:
        blocked.append("no checks ran on the head commit")
    if pending:
        blocked.append(f"checks still running: {', '.join(pending)}")
    if failed:
        blocked.append(f"checks not green: {', '.join(failed)}")

    threads = review_threads(owner, name, number)
    author = pr["author"]["login"]
    unresolved = sum(not thread["isResolved"] for thread in threads)
    silent = sum(
        thread["isResolved"]
        and not any(
            (comment.get("author") or {}).get("login") == author
            for comment in thread["comments"]["nodes"][1:]
        )
        for thread in threads
    )
    if unresolved:
        blocked.append(f"{unresolved} review thread(s) unresolved")
    if silent:
        blocked.append(f"{silent} thread(s) resolved without a reply from {author}")
    diff = gh("pr", "diff", number, "-R", repo)
    merge_base = gh(
        "api", f"repos/{repo}/compare/{pr['baseRefOid']}...{sha}", "--jq", ".merge_base_commit.sha"
    ).strip()
    findings = list(dict.fromkeys(
        scope_findings(diff) + workflow_changes(diff, read_at(repo, merge_base), read_at(repo, sha))
    ))
    bump_failures = ["not Dependabot"]
    if DEPENDABOT_VERSION_ONLY and author in DEPENDABOT_AUTHORS:
        commits = gh_json_lines(
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{number}/commits?per_page=100",
            "--jq",
            ".[]|{author:.author.login,verified:.commit.verification.verified,"
            "message:.commit.message}",
        )
        bump_failures = dependabot_bump_failures(author, pr["headRefName"], commits, diff)
        for reason in bump_failures:
            print(f"NOTE  not a Dependabot version-only bump: {reason}")
    if not bump_failures:
        print("NOTE  Dependabot version-only bump: exact-head checks are its verification")
        findings = dependabot_scope(findings)
    elif not has_verification(pr["body"] or ""):
        blocked.append("no '## Verification' section with commands and results")
    print(f"{repo}#{number} at {sha[:12]}: {len(runs)} check runs, {len(threads)} threads")
    for category, description in findings:
        print(f"DECISION {category}: {description}")
    if blocked:
        for reason in blocked:
            print(f"BLOCKED  {reason}")
        print("verdict: BLOCKED")
        return 1

    try:
        rules, judge = load_policy(policy_path)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"PARK  decision policy is invalid: {exc}")
        print("verdict: PARK")
        return 10
    evidence_failures = required_check_failures(runs, judge["required_checks"], workflow_runs, sha)
    evidence_failures.extend(
        evidence_policy_failures(diff, _head_stage_references(repo, sha, diff))
    )
    if evidence_failures:
        for reason in evidence_failures:
            print(f"BLOCKED  {reason}")
        print("verdict: BLOCKED")
        return 1
    comments = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{number}/comments?per_page=100",
        "--jq",
        ".[]|{body,author:.user.login,created_at}",
    )
    decision = judge_decision(comments, sha, judge["trusted_author"])
    labels = {label["name"] for label in pr["labels"]}
    owner_events = gh_json_lines(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{number}/events?per_page=100",
        "--jq",
        '.[]|select(.label.name=="owner-approved")'
        "|{event,actor:.actor.login,label:.label.name,created_at}",
    )
    head_checks_started = max((str(run.get("started_at") or "") for run in runs), default="")
    current_owner_approval = owner_label_approval(
        owner_events, owner, head_checks_started
    ) or owner_comment_approval(comments, owner, sha, head_checks_started)
    verdict, reasons = decide(
        findings,
        rules,
        labels,
        decision,
        current_owner_approval,
    )
    for reason in reasons:
        print(f"{verdict}  {reason}")
    print(f"verdict: {verdict}")
    if verdict == "READY":
        if "--merge" in argv:
            merge_pull_request(number, repo, sha)
            print(f"merged {repo}#{number} at {sha}")
        else:
            print(
                f"merge: rerun this gate with --merge; GitHub will require the checked head {sha}"
            )
    return {"READY": 0, "BLOCKED": 1, "PARK": 10, "JUDGE": 11}[verdict]


def load_scope(path: Path) -> tuple[str, bool]:
    """Read the repository's merge-authority paths and Dependabot opt-in, failing closed."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    scope = data.get("scope")
    paths = scope.get("merge_authority") if isinstance(scope, dict) else None
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(p, str) or not p.startswith("^") for p in paths)
    ):
        raise ValueError("policy needs scope.merge_authority: a list of ^-anchored patterns")
    for pattern in paths:
        re.compile(pattern)
    dependabot = data.get("dependabot", {})
    version_only = dependabot.get("version_only", False) if isinstance(dependabot, dict) else None
    if not isinstance(version_only, bool):
        raise ValueError("dependabot.version_only must be true or false")
    return "|".join(f"(?:{p})" for p in paths), version_only


# The engine itself is always merge authority, whatever a repository's policy
# lists, so an agent can never edit the code that judges its own changes.
ENGINE_PATHS = r"^mandate/"


def configure(merge_authority: str, dependabot_version_only: bool) -> None:
    """Install one repository's merge-authority pattern and Dependabot opt-in."""
    global PATH_RULES, DEPENDABOT_VERSION_ONLY
    PATH_RULES = (
        (
            "merge-authority",
            re.compile(f"(?:{ENGINE_PATHS})|{merge_authority}"),
            "merge authority changed",
        ),
        *COMMON_PATH_RULES,
    )
    DEPENDABOT_VERSION_ONLY = dependabot_version_only


def cli(argv: list[str], policy_path: Path, self_test: Callable[[], int]) -> int:
    """Entry point for a repository: bind its policy, then self-test or decide."""
    try:
        configure(*load_scope(policy_path))
    except (OSError, ValueError, re.error, tomllib.TOMLDecodeError) as exc:
        print(f"PARK  decision policy is invalid: {exc}")
        print("verdict: PARK")
        return 10
    if argv == ["--self-test"]:
        return self_test()
    return main(argv, policy_path)
