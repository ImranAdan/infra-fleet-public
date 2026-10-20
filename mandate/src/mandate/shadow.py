"""Shadow decision for one live pull request (KAN-27 adapter, D-23).

Translates immutable provider objects into the G2 ``DecisionInput`` and runs
the same ``decide()``; it adds no outcome or reason of its own. It only reads:
it never merges, labels, comments or approves, so its output grants nothing.

    python3 -m mandate.shadow ImranAdan/infra-fleet-public 222 --delegation-sha <sha>

ponytail: facts (permission/secret/trigger deltas, signatures) are not
computed yet, so classes that match on them never match and fail closed; and
mechanical refusals (head/base drift, reviews, enforcement, ledger) belong to
the executor (KAN-28), so ``blocking`` is empty here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mandate import decision as m
from mandate import delegation as d
from mandate import evidence as e
from mandate import gate

ADAPTER_VERSION = 1
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


def _reader(repository: str, ref: str):
    """Read files at the trusted base commit; a missing file is None."""

    def read(path: str) -> str | None:
        try:
            return _gh(
                "api",
                "-H",
                "Accept: application/vnd.github.raw+json",
                f"repos/{repository}/contents/{path}?ref={ref}",
            )
        except subprocess.CalledProcessError:
            return None

    return read


def findings(
    diff: str, paths: list[str], delegation: d.Delegation, read
) -> tuple[tuple[str, str], ...]:
    """(category, path) per changed path; anything unattributable still counts."""
    found = gate.scope_findings(diff)
    out: list[tuple[str, str]] = []
    claimed: set[int] = set()
    for path in paths:
        cats = set()
        for index, (category, description) in enumerate(found):
            if path in description:  # over-attribution only restricts more
                cats.add(category)
                claimed.add(index)
        cats |= {c for c, _ in d.reserved_findings(delegation, [path], read)}
        out += [(c, path) for c in sorted(cats)] or [("unclassified", path)]
    out += [
        (c, description) for i, (c, description) in enumerate(found) if i not in claimed
    ]
    return tuple(out)


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
    return m.DecisionInput(
        delegation=delegation,
        subject=subject,
        findings=findings(diff, paths, delegation, _reader(repository, base)),
        facts={},
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
    print(
        json.dumps(
            {
                "adapter_version": ADAPTER_VERSION,
                "pull_request": args.number,
                **decision.to_dict(),
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
