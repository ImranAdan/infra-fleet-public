#!/usr/bin/env python3
"""Replay an export offline and report it against the frozen dictionary.

    PYTHONPATH=<engine>/mandate/src python3 mandate/replay/report.py <export> [--json <out>]

Nothing reaches GitHub: gh is replaced by the export's recorded responses,
and a call the export lacks is an error, never a live fetch. Populations are
recomputed from the recorded events and must equal the manifest's. Each pull
request is decided by the real shadow.inputs() and decide(); each item's
historical path and authority class come from its recorded comments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402

from mandate import decision as m  # noqa: E402
from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import gate, shadow  # noqa: E402

APPROVE = re.compile(r"^/approve ([0-9a-f]{40})$")


class Export:
    """gh answered from a recorded export only."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = json.loads((root / "manifest.json").read_text())
        self.calls = {json.dumps(c["args"]): c for c in self.manifest["calls"]}

    def gh(self, *args: str) -> str:
        call = self.calls.get(json.dumps(list(args)))
        if call is None:
            raise LookupError(f"not in the export: gh {' '.join(args)}")
        if call["returncode"]:
            raise subprocess.CalledProcessError(call["returncode"], ["gh", *args], stderr=call["stderr"])
        data = (self.root / "calls" / f"{call['stdout_sha256']}.out").read_bytes()
        if hashlib.sha256(data).hexdigest() != call["stdout_sha256"]:
            raise ValueError(f"export file for gh {' '.join(args)} does not match its digest")
        return data.decode()

    def lines(self, *args: str) -> list[dict]:
        return [json.loads(x) for x in self.gh("api", "--paginate", *args).splitlines() if x.strip()]


def path_of(pr: dict, comments: list[dict], spec: dict) -> str:
    """The item's historical path, first match in the dictionary's order."""
    if pr.get("merged_at"):
        head = pr["head"]["sha"]
        for c in comments:
            if ((c.get("user") or {}).get("login") == spec["owner"] and c["created_at"] <= pr["merged_at"]
                    and (match := APPROVE.match((c.get("body") or "").strip())) and match.group(1) == head):
                return "head-bound approval"
        merger = (pr.get("merged_by") or {}).get("login")
        return "worker merge" if merger == spec["worker"] else "owner-principal merge without approval"
    return "closed unmerged" if pr.get("state") == "closed" else "open"


def authority(comments: list[dict], spec: dict) -> list[str]:
    """Authority categories the gate's own PARK comments named for the item."""
    found = set()
    for c in comments:
        body = c.get("body") or ""
        if (c.get("user") or {}).get("login") == spec["worker"] and "owner decision required" in body:
            found |= {cat for cat in spec["paths"]["authority_categories"] if re.search(rf"\b{re.escape(cat)}\b", body)}
    return sorted(found)


def self_test() -> int:
    spec = tomllib.loads(collect.DICTIONARY.read_text())
    head, other = "a" * 40, "b" * 40
    merged = {"merged_at": "2026-10-10T00:00:00Z", "head": {"sha": head}, "merged_by": {"login": "github-actions[bot]"}}
    owner = lambda body, at="2026-10-09T00:00:00Z", who="ImranAdan": {"user": {"login": who}, "created_at": at, "body": body}  # noqa: E731
    assert path_of(merged, [owner(f"/approve {head}")], spec) == "head-bound approval"
    assert path_of(merged, [owner(f"/approve {other}")], spec) == "worker merge"  # another head binds nothing
    assert path_of(merged, [owner(f"/approve {head}", at="2026-10-11T00:00:00Z")], spec) == "worker merge"  # after the merge
    assert path_of(merged, [owner(f"/approve {head}", who="someone")], spec) == "worker merge"
    assert path_of({**merged, "merged_by": {"login": "ImranAdan"}}, [], spec) == "owner-principal merge without approval"
    assert path_of({"merged_at": None, "state": "closed"}, [], spec) == "closed unmerged"
    assert path_of({"merged_at": None, "state": "open"}, [], spec) == "open"
    park = {"user": {"login": "github-actions[bot]"}, "body": "PARK: owner decision required for `merge-authority`, `permission-added`."}
    assert authority([park, owner("owner decision required for `credential`")], spec) == ["merge-authority", "permission-added"]
    print("report self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    if (argv if argv is not None else sys.argv[1:]) == ["--self-test"]:
        return self_test()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    spec = tomllib.loads(collect.DICTIONARY.read_text())
    ex = Export(args.export)
    man = ex.manifest
    if man["dictionary"]["sha256"] != hashlib.sha256(collect.DICTIONARY.read_bytes()).hexdigest():
        raise SystemExit("the export was collected under another dictionary version")
    gate.gh = ex.gh
    gate.configure(*gate.load_scope(Path(shadow.__file__).parents[3] / shadow.POLICY))

    # Populations, recomputed from the recorded events alone.
    cutoff, start = spec["windows"]["discovery_cutoff"], spec["windows"]["sample_start"]
    pops: dict[str, list[list]] = {p["id"]: [] for p in spec["population"]}
    delegations = {}
    for repository in spec["repositories"]:
        events = ex.lines(f"repos/{repository}/issues/events?per_page=100", "--jq", ".[]")
        ever, at = collect.membership(events, spec["label"], cutoff)
        census, _ = collect.membership(events, spec["label"], man["collected_at"])
        pops["ever-labelled"] += [[repository, n, k] for n, k in sorted(ever.items())]
        pops["labelled-at-cutoff"] += [[repository, n, "pull"] for n in at]
        pops["ever-labelled-census"] += [[repository, n, k] for n, k in sorted(census.items())]
        pops["worker-merges"] += [[repository, n, "pull"] for n in collect.worker_merges(
            events, spec["worker"], start, cutoff) if n not in census]
        try:
            delegations[repository] = collect.delegation_for(ex, repository, man["delegation"]["commit"])
        except d.DelegationError as exc:
            delegations[repository] = exc
    if pops != man["populations"]:
        raise SystemExit("populations recomputed from the export differ from the manifest")

    rows = []
    items = sorted({tuple(x) for x in pops["ever-labelled-census"]} | {tuple(x) for x in man["sample"]["chosen"]})
    for repository, number, kind in items:
        comments = ex.lines(f"repos/{repository}/issues/{number}/comments?per_page=100", "--jq", ".[]")
        row = {"repository": repository, "number": number, "kind": kind, "authority_categories": authority(comments, spec)}
        if kind == "issue":
            issue = json.loads(ex.gh("api", f"repos/{repository}/issues/{number}"))
            row.update(path="open" if issue["state"] == "open" else "closed unmerged", outcome="not replayed (issue)", reasons=[])
            rows.append(row)
            continue
        pr = json.loads(ex.gh("api", f"repos/{repository}/pulls/{number}"))
        deleg = delegations[repository]
        try:
            if isinstance(deleg, d.Delegation):
                snapshot = shadow.inputs(repository, number, deleg)
            else:  # as shadow.main(): an unusable delegation decides alone
                error = deleg or d.DelegationError("DELEGATION_INVALID", f"no delegation for {repository} at the pin")
                snapshot = m.DecisionInput(error, e.Subject(repository, pr["head"]["sha"], pr["base"]["sha"], ""), (), {}, (), ())
            decision = m.decide(snapshot)
            row.update(outcome=decision.outcome, reasons=[r.code for r in decision.reasons])
        except Exception as exc:  # noqa: BLE001 - reported, never dropped
            row.update(outcome="replay error", reasons=[f"{type(exc).__name__}: {exc}"[:200]])
        row["path"] = path_of(pr, comments, spec)
        rows.append(row)

    unsafe = [r for r in rows if r["authority_categories"] and r["outcome"] == "AUTHORIZE"]
    matrix = Counter((r["path"], r["outcome"]) for r in rows)
    disagreements = []
    for r in rows:
        rule = ("authority class and not ESCALATE" if r["authority_categories"] and r["outcome"] not in ("ESCALATE", "not replayed (issue)")
                else "worker merge and not AUTHORIZE" if r["path"] == "worker merge" and r["outcome"] != "AUTHORIZE"
                else "head-bound approval or owner-principal merge, and AUTHORIZE"
                if r["path"] in ("head-bound approval", "owner-principal merge without approval") and r["outcome"] == "AUTHORIZE"
                else None)
        if rule:
            disagreements.append({**{k: r[k] for k in ("repository", "number", "path", "outcome", "reasons", "authority_categories")},
                                  "rule": rule, "reviewer": "", "verdict": "", "note": ""})
    engine = Path(shadow.__file__).resolve().parents[2]
    report = {
        "export": {"collected_at": man["collected_at"], "engine_collected": man["engine"], "delegation": man["delegation"],
                   "manifest_sha256": hashlib.sha256((args.export / "manifest.json").read_bytes()).hexdigest()},
        "engine_replayed": subprocess.run(["git", "-C", str(engine), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "attribution": spec["attribution"],
        "population_counts": {k: {"total": len(v), "pull": sum(1 for x in v if x[2] == "pull"),
                                  "issue": sum(1 for x in v if x[2] == "issue")} for k, v in pops.items()},
        "unsafe_authorizations": len(unsafe),
        "outcome_by_path": {f"{p} -> {o}": n for (p, o), n in sorted(matrix.items())},
        "disagreements": disagreements,
        "rows": rows,
    }
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: report[k] for k in ("population_counts", "unsafe_authorizations", "outcome_by_path")}, indent=1, sort_keys=True))
    print(f"disagreements for review: {len(disagreements)}; replay errors: {sum(1 for r in rows if r['outcome'] == 'replay error')}")
    return 1 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
