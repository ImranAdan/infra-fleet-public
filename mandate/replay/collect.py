#!/usr/bin/env python3
"""Collect the historical replay export: every provider response the replay
reads, kept byte for byte with its SHA-256.

    PYTHONPATH=<engine>/mandate/src python3 mandate/replay/collect.py <out> --delegation-sha <sha>

Read-only. Population queries (dictionary.toml), each item's historical-path
inputs and the exact calls the real shadow.inputs() makes all go through one
recorder around gh, so a replay that serves the same bytes back to the same
code sees what the engine saw. <out> gets calls/<sha256>.out (content
addressed) and manifest.json.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from mandate import delegation as d
from mandate import gate, shadow

HERE = Path(__file__).resolve().parent
DICTIONARY = HERE / "dictionary.toml"


class Recorder:
    """gh with every call's arguments, exit status and output recorded once."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.calls: dict[str, dict] = {}
        (out / "calls").mkdir(parents=True, exist_ok=True)

    def gh(self, *args: str) -> str:
        key = json.dumps(args)
        if key not in self.calls:
            for _ in range(3):  # a dropped connection is retried; an HTTP 4xx is an answer
                result = subprocess.run(["gh", *args], capture_output=True, text=True)  # noqa: S603, S607
                if not result.returncode or re.search(r"HTTP 4\d\d", result.stderr):
                    break
            digest = hashlib.sha256(result.stdout.encode()).hexdigest()
            (self.out / "calls" / f"{digest}.out").write_text(result.stdout)
            self.calls[key] = {"args": list(args), "returncode": result.returncode, "stdout_sha256": digest,
                               "stderr": result.stderr.strip() if result.returncode else ""}
        call = self.calls[key]
        if call["returncode"]:
            raise subprocess.CalledProcessError(call["returncode"], ["gh", *args], stderr=call["stderr"])
        return (self.out / "calls" / f"{call['stdout_sha256']}.out").read_text()

    def lines(self, *args: str) -> list[dict]:
        return [json.loads(x) for x in self.gh("api", "--paginate", *args).splitlines() if x.strip()]


def membership(events: list[dict], label: str, until: str) -> tuple[dict[int, str], list[int]]:
    """Items ever labelled, with their kind, and pull requests carrying the label, at ``until``."""
    ever: dict[int, str] = {}
    last: dict[int, str] = {}
    for ev in sorted(events, key=lambda e: (e["created_at"], e["id"])):
        if ev.get("event") not in ("labeled", "unlabeled") or (ev.get("label") or {}).get("name") != label:
            continue
        if ev["created_at"] > until:
            continue
        number = ev["issue"]["number"]
        if ev["event"] == "labeled":
            ever[number] = "pull" if ev["issue"].get("pull_request") is not None else "issue"
        last[number] = ev["event"]
    return ever, sorted(n for n, e in last.items() if e == "labeled" and ever.get(n) == "pull")


def worker_merges(events: list[dict], worker: str, start: str, end: str) -> list[int]:
    return sorted({ev["issue"]["number"] for ev in events
                   if ev.get("event") == "merged" and (ev.get("actor") or {}).get("login") == worker
                   and start <= ev["created_at"] <= end})


def git(where: Path, *args: str) -> str:
    """git's answer in ``where``, or "" without git or outside a checkout."""
    try:
        return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def pin(where: Path) -> dict:
    return {"commit": git(where, "rev-parse", "HEAD"), "clean": git(where, "status", "--porcelain", "--", ".") == ""}


def delegation_for(rec: Recorder, repository: str, sha: str):
    """The pinned delegation, read the way delegation.fetch() reads it; None if the pin has none."""
    path = d.path_for(repository)
    try:
        text = rec.gh("api", "-H", "Accept: application/vnd.github.raw+json",
                      f"repos/{d.DELEGATION_REPOSITORY}/contents/{path}?ref={sha}")
    except subprocess.CalledProcessError:
        return None
    return d.parse(text, repository, f"{d.DELEGATION_REPOSITORY}@{sha}:{path}")


def self_test() -> int:
    ev = lambda i, t, e, n, label="needs-decision", pr=True, actor="x": {  # noqa: E731
        "id": i, "created_at": t, "event": e, "label": {"name": label}, "actor": {"login": actor},
        "issue": {"number": n, **({"pull_request": {}} if pr else {})}}
    events = [
        ev(1, "2026-10-01T00:00:00Z", "labeled", 7),
        ev(2, "2026-10-02T00:00:00Z", "unlabeled", 7),  # labelled once, cleared before the cut-off
        ev(3, "2026-10-03T00:00:00Z", "labeled", 8),
        ev(4, "2026-10-03T00:00:00Z", "labeled", 9, pr=False),  # an issue: ever, never at the cut-off
        ev(5, "2026-10-20T00:00:00Z", "labeled", 10),  # after the cut-off: census only
        ev(6, "2026-10-04T00:00:00Z", "labeled", 11, label="other"),
        ev(7, "2026-10-05T00:00:00Z", "merged", 12, actor="github-actions[bot]"),
        ev(8, "2026-10-05T00:00:00Z", "merged", 13, actor="ImranAdan"),
        ev(9, "2026-09-01T00:00:00Z", "merged", 14, actor="github-actions[bot]"),  # before the window
    ]
    cutoff = "2026-10-15T23:59:59Z"
    assert membership(events, "needs-decision", cutoff) == ({7: "pull", 8: "pull", 9: "issue"}, [8])
    assert membership(events, "needs-decision", "2026-10-27T00:00:00Z")[0] == {7: "pull", 8: "pull", 9: "issue", 10: "pull"}
    assert worker_merges(events, "github-actions[bot]", "2026-09-25T00:00:00Z", cutoff) == [12]
    print("collect self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    if (argv if argv is not None else sys.argv[1:]) == ["--self-test"]:
        return self_test()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--delegation-sha", required=True)
    args = parser.parse_args(argv)
    if not d.COMMIT_SHA.fullmatch(args.delegation_sha):
        parser.error("--delegation-sha must be a full commit SHA")
    spec = tomllib.loads(DICTIONARY.read_text())
    # Pins are taken before anything is read, from clean checkouts, and checked
    # again at the end: a concurrent edit cannot change what is reported.
    engine = Path(shadow.__file__).resolve().parents[2]  # the engine's mandate/ directory
    pins = {"engine_start": pin(engine), "tooling": pin(HERE)}
    for name, value in pins.items():
        if not value["commit"] or not value["clean"]:
            parser.error(f"{name} must be a clean git checkout: {value}")
    started_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = Recorder(args.out)
    gate.gh = rec.gh  # shadow reads the provider through gate.gh
    gate.configure(*gate.load_scope(Path(shadow.__file__).parents[3] / shadow.POLICY))
    collected_at = started_at
    cutoff, start = spec["windows"]["discovery_cutoff"], spec["windows"]["sample_start"]

    populations: dict[str, list[list]] = {p["id"]: [] for p in spec["population"]}
    merges: list[list] = []
    repositories, delegations = {}, {}
    for repository in spec["repositories"]:
        repositories[repository] = json.loads(rec.gh("api", f"repos/{repository}"))["id"]
        delegations[repository] = delegation_for(rec, repository, args.delegation_sha)
        events = rec.lines(f"repos/{repository}/issues/events?per_page=100", "--jq", ".[]")
        ever, at_cutoff = membership(events, spec["label"], cutoff)
        census, _ = membership(events, spec["label"], collected_at)
        populations["ever-labelled"] += [[repository, n, k] for n, k in sorted(ever.items())]
        populations["labelled-at-cutoff"] += [[repository, n, "pull"] for n in at_cutoff]
        populations["ever-labelled-census"] += [[repository, n, k] for n, k in sorted(census.items())]
        merges += [[repository, n, "pull"] for n in worker_merges(events, spec["worker"], start, cutoff) if n not in census]
    populations["worker-merges"] = merges
    sample = spec["sample"]
    chosen = sorted(merges) if len(merges) <= sample["size"] else sorted(
        random.Random(sample["seed"]).sample(sorted(merges), sample["size"]))

    items = {tuple(x) for x in populations["ever-labelled-census"]} | {tuple(x) for x in chosen}
    errors = []
    for repository, number, kind in sorted(items):
        rec.lines(f"repos/{repository}/issues/{number}/comments?per_page=100", "--jq", ".[]")
        if kind == "issue":
            rec.gh("api", f"repos/{repository}/issues/{number}")
            continue
        deleg = delegations[repository] or d.Delegation(repository, "shadow", spec["owner"], (), (), (), "")
        try:  # the exact calls the engine makes for this pull request
            shadow.inputs(repository, number, deleg)
        except Exception as exc:  # noqa: BLE001 - recorded, never dropped
            errors.append([repository, number, f"{type(exc).__name__}: {exc}"[:300]])

    pins["engine_end"] = pin(engine)
    if pins["engine_end"] != pins["engine_start"]:
        raise SystemExit(f"the engine changed during collection: {pins}")
    manifest = {
        "protocol": 2,
        "finished_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **pins,
        "dictionary": {"version": spec["version"], "sha256": hashlib.sha256(DICTIONARY.read_bytes()).hexdigest()},
        "collected_at": collected_at,
        "gh": subprocess.run(["gh", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        "repositories": repositories,
        "engine": pins["engine_start"],
        "delegation": {"repository": d.DELEGATION_REPOSITORY, "commit": args.delegation_sha,
                       "covers": [r for r, x in delegations.items() if x is not None]},
        "populations": populations,
        "sample": {**sample, "chosen": chosen},
        "errors": errors,
        "calls": sorted(rec.calls.values(), key=lambda c: c["args"]),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    counts = {k: len(v) for k, v in populations.items()}
    print(json.dumps({"counts": counts, "sampled": len(chosen), "items": len(items), "calls": len(rec.calls),
                      "errors": len(errors)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
