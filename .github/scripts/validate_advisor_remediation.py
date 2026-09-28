#!/usr/bin/env python3
"""Fail unless a patch is exactly a registered ignore-unfixed removal."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DIFF_PATH = re.compile(r"^diff --git a/(\S+) b/(\S+)$")
ALLOWED_REMOVAL = re.compile(r"^-\s*ignore-unfixed\s*:\s*(['\"]?)[Tt][Rr][Uu][Ee]\1\s*$")


def validate(lines: list[str]) -> None:
    paths: list[str] = []
    changes: list[str] = []
    for line in lines:
        match = DIFF_PATH.fullmatch(line)
        if match:
            old, new = match.groups()
            if old != new:
                raise ValueError("registered remediation cannot rename files")
            paths.append(new)
            continue
        if line.startswith(("Binary files ", "GIT binary patch")):
            raise ValueError("registered remediation cannot contain binary data")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            changes.append(line)

    if not paths or any(
        not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml"))
        for path in paths
    ):
        raise ValueError("registered remediation may change workflow YAML only")
    if not changes or any(not ALLOWED_REMOVAL.fullmatch(line) for line in changes):
        raise ValueError("patch exceeds the registered ignore-unfixed removal")


def self_test() -> int:
    valid = [
        "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml",
        "--- a/.github/workflows/ci.yml",
        "+++ b/.github/workflows/ci.yml",
        "@@ -1 +0,0 @@",
        "-          ignore-unfixed: true",
    ]
    validate(valid)
    for invalid in (
        [*valid, "+          ignore-unfixed: false"],
        [line.replace(".github/workflows/ci.yml", "README.md") for line in valid],
        [*valid[:-1], "-          severity: LOW"],
        [*valid, "GIT binary patch"],
    ):
        try:
            validate(invalid)
        except ValueError:
            continue
        raise AssertionError(f"invalid patch passed: {invalid!r}")
    print("self-test passed")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} PATCH", file=sys.stderr)
        return 2
    try:
        validate(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"invalid advisor remediation: {exc}", file=sys.stderr)
        return 1
    print("advisor remediation patch is within the registered boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
