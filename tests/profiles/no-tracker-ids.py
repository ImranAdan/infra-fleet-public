#!/usr/bin/env python3
"""Code and docs name things by what they do, never by planning or tracker
IDs: Jira keys, gate codes, Confluence decision and case numbers, review
rounds. Those mean nothing to a reader of the repository and go stale; they
belong in pull request and commit text only. Run: tests/profiles/no-tracker-ids.py
"""

import re
import subprocess
import sys

IDS = re.compile(r"\b(?:KAN-\d+|G[0-4]|D-\d+|A-\d+|TDR-\d+|R\d-F\d)\b|Codex (?:bot|F\d|R\d)")
SKIP = ("applications/",)  # the app templates' SVG path data looks like IDs


def main() -> int:
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    found = []
    for name in filter(None, files.split("\0")):
        if name.startswith(SKIP):
            continue
        try:
            with open(name, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError):  # binary or a removed path
            continue
        found += [f"{name}:{n}: {line.strip()}" for n, line in enumerate(lines, 1) if IDS.search(line)]
    if found:
        print("\n".join(found), file=sys.stderr)
        print(f"FAIL  {len(found)} line(s) name tracker IDs: say what the thing does instead", file=sys.stderr)
        return 1
    print("PASS  no tracker IDs in code or docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
