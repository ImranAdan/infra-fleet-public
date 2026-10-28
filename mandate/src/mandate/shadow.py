"""Shadow decision for one live pull request.

Translates immutable provider objects into the decision's ``DecisionInput`` and runs
the same ``decide()``; it adds no outcome or reason of its own. It only reads:
it never merges, labels, comments or approves, so its output grants nothing.

    python3 -m mandate.shadow ImranAdan/infra-fleet-public 222 --delegation-sha <sha>

It proves ``lockfile_sibling`` (see ``facts()``). ponytail: the other facts
(permission/secret/trigger deltas, author, signatures) are not computed yet,
so classes that match on them never match and fail closed; and mechanical
refusals (head/base drift, reviews, enforcement, ledger, an unregistered
proposer) belong to the live merge executor, so ``blocking`` is empty here.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import posixpath
import re
import sys
from pathlib import Path
from typing import Any

from mandate import decision as m
from mandate import delegation as d
from mandate import evidence as e
from mandate import gate
from mandate import receipt as rc

ADAPTER_VERSION = 2
# Each manifest's resolved lockfile, by ecosystem.
LOCKFILES = {"pyproject.toml": "uv.lock", "package.json": "package-lock.json", "go.mod": "go.sum"}
REQUIREMENTS = re.compile(r"(?:^|/)requirements[^/]*\.txt$")
EXACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?\s*===?\s*[^\s*,;<>=!~]+")
INCLUDE = re.compile(r"(?:-r|-c|--requirement|--constraint)(?:\s+|=)(\S+)$")
POLICY = Path(".claude/skills/merge-gate/decision-policy.toml")


def _gh(*args: str) -> str:
    return gate.gh(*args)


def _lines(*args: str) -> list[dict[str, Any]]:
    """Paginated API items, one JSON object per line from ``--jq``."""
    return [
        json.loads(line)
        for line in _gh("api", "--paginate", *args).splitlines()
        if line.strip()
    ]


def _per_file(diff: str) -> dict[str, str]:
    """The unified diff split by file, keyed by its new path; a rename's old
    path is also a key (with the same chunk), so a moved file keeps its past."""
    chunks: dict[str, str] = {}
    for chunk in re.split(r"(?m)^(?=diff --git )", diff):
        header = re.match(r"diff --git a/(.*) b/(.*)$", chunk, re.M)
        if header:
            for name in dict.fromkeys(header.groups()):
                chunks[name] = chunks.get(name, "") + chunk
    return chunks


def findings(
    diff: str, paths: list[str], delegation: d.Delegation, read, read_head=lambda path: None, read_from=None
) -> tuple[tuple[str, str], ...]:
    """(category, path) per changed path, classified from that file's own diff
    and, for a workflow, from its parsed versions (``read_from`` at the merge
    base, default ``read``; ``read_head`` at the head; a workflow it cannot
    read counts as a permission change). Reserved surfaces are read with
    ``read``, at the trusted base.

    A file in the diff but not in ``paths`` still contributes its findings.
    """
    chunks = _per_file(diff)
    out: list[tuple[str, str]] = []
    for path in dict.fromkeys([*paths, *chunks]):
        cats = {c for c, _ in gate.scope_findings(chunks.get(path, ""))}
        cats |= {c for c, _ in gate.workflow_changes(chunks.get(path, ""), read_from or read, read_head)}
        cats |= {c for c, _ in d.reserved_findings(delegation, [path], read)}
        out += [(c, path) for c in sorted(cats)] or [("unclassified", path)]
    return tuple(out)


def _pinned(path: str, read, seen: set[str]) -> bool:
    """A requirements file at the head, and every file it includes, names one
    exact version per requirement. Any option other than an include or a hash
    is unproven, and so is an include outside the repository."""
    if path in seen:
        return True
    seen.add(path)
    text = read(path)
    if text is None:
        return False
    for line in re.sub(r"\\\n", " ", text).splitlines():
        line = re.sub(r"(?:^|\s)#.*", "", line)
        line = re.sub(r"\s--hash[=\s]\S+", "", " " + line).strip()
        include = INCLUDE.match(line)
        if include:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), include.group(1)))
            if target.startswith("../") or not _pinned(target, read, seen):
                return False
        elif line and not EXACT.fullmatch(line.split(";", 1)[0].strip()):
            return False
    return True


def facts(found: tuple[tuple[str, str], ...], paths: list[str], read_head) -> dict[str, Any]:
    """Class facts proven from this change's files at the head; a fact it
    cannot prove is absent or false, so its classes refuse.

    ``lockfile_sibling``: every changed dependency manifest is resolved here.
    A manifest whose ecosystem has a lockfile changes it alongside, a lockfile
    still exists, and a requirements file (its own lockfile) pins exactly.
    """
    changed = set(paths)

    def resolved(path: str) -> bool:
        parent, name = posixpath.split(path)
        if name in LOCKFILES:  # the lockfile is a manifest too, so it is read below
            return posixpath.join(parent, LOCKFILES[name]) in changed
        if REQUIREMENTS.search(path):
            return _pinned(path, read_head, set())
        return name in LOCKFILES.values() and read_head(path) is not None

    manifests = sorted({p for c, p in found if c == "dependency-manifest"})
    return {"lockfile_sibling": all(map(resolved, manifests))} if manifests else {}


def inputs(repository: str, number: int, delegation: d.Delegation) -> m.DecisionInput:
    pr = json.loads(_gh("api", f"repos/{repository}/pulls/{number}"))
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    subject = e.Subject(repository, head, base, delegation.source)
    paths = [
        f["filename"]
        for f in _lines(
            f"repos/{repository}/pulls/{number}/files?per_page=100", "--jq", ".[]"
        )
    ]
    diff = _gh("pr", "diff", str(number), "-R", repository)
    # The diff runs from the merge base, so the parsed comparison does too.
    merge_base = _gh(
        "api", f"repos/{repository}/compare/{base}...{head}", "--jq", ".merge_base_commit.sha"
    ).strip()
    checks = _lines(
        f"repos/{repository}/commits/{head}/check-runs?per_page=100",
        "--jq",
        ".check_runs[]",
    )
    runs = {
        r["check_suite_id"]: r
        for r in _lines(
            f"repos/{repository}/actions/runs?head_sha={head}&per_page=100",
            "--jq",
            ".workflow_runs[]",
        )
    }
    records = tuple(
        e.normalize(c, runs.get((c.get("check_suite") or {}).get("id")), subject)
        for c in checks
    )
    read_head = gate.read_at(repository, head)
    found = findings(diff, paths, delegation, gate.read_at(repository, base), read_head,
                     gate.read_at(repository, merge_base))
    return m.DecisionInput(
        delegation=delegation,
        subject=subject,
        findings=found,
        facts=facts(found, paths, read_head),
        records=records,
        blocking=(),
    )


def summary(number: int, decision: m.Decision) -> str:
    rows = "\n".join(
        f"| `{r.code}` | {r.outcome} | {r.owner} | {r.detail[:200]} |"
        for r in decision.reasons
    )
    return (
        f"## Mandate shadow decision for #{number}: **{decision.outcome}**\n\n"
        f"Head `{decision.subject.head_sha}`, base `{decision.subject.base_sha}`, policy `{decision.policy}`. "
        "Shadow mode: this decision grants nothing.\n\n"
        + (
            f"| Reason | Outcome | Next | Detail |\n|---|---|---|---|\n{rows}\n"
            if rows
            else "No reasons: every finding is delegated and proven.\n"
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repository")
    parser.add_argument("number", type=int)
    parser.add_argument("--delegation-sha", required=True)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument(
        "--summary", type=Path, help="also append a Markdown summary here"
    )
    args = parser.parse_args(argv)
    gate.configure(*gate.load_scope(args.policy))
    try:
        delegation: d.Delegation | d.DelegationError = d.fetch(
            args.repository, args.delegation_sha
        )
    except d.DelegationError as exc:
        delegation = exc
    if isinstance(delegation, d.DelegationError):
        pr = json.loads(_gh("api", f"repos/{args.repository}/pulls/{args.number}"))
        subject = e.Subject(args.repository, pr["head"]["sha"], pr["base"]["sha"], "")
        snapshot = m.DecisionInput(delegation, subject, (), {}, (), ())
    else:
        snapshot = inputs(args.repository, args.number, delegation)
    decision = m.decide(snapshot)
    # The receipt this decision would record; shadow mode writes no ledger.
    receipt = rc.build(
        decision,
        args.number,
        "shadow",
        versions={"adapter": ADAPTER_VERSION, "code": os.environ.get("GITHUB_SHA", "local")},
        actors={"run_id": os.environ.get("GITHUB_RUN_ID", "local")},
        evaluated_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    print(
        json.dumps(
            {
                "adapter_version": ADAPTER_VERSION,
                "pull_request": args.number,
                **decision.to_dict(),
                "receipt": receipt,
            },
            sort_keys=True,
        )
    )
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(summary(args.number, decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
