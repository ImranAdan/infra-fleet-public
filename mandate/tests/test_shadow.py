"""Shadow adapter checks (KAN-27). Run: python3 mandate/tests/test_shadow.py

Provider responses are canned and shaped like the REST API; the adapter and
decide() are the real code. Nothing here calls GitHub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import (
    gate,  # noqa: E402
    shadow,  # noqa: E402
)

REPO = "ImranAdan/infra-fleet-public"
HEAD, BASE = "a" * 40, "b" * 40
POLICY = f"{d.DELEGATION_REPOSITORY}@{'d' * 40}:repositories/infra-fleet-public.toml"
DELEGATION = d.parse(
    (HERE.parent / "examples" / "infra-fleet-public.toml").read_text(), REPO, POLICY
)
INTENT = "Intent gate / Declared intent"


def diff(*paths: str) -> str:
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new\n"
        for p in paths
    )


def provider(paths: tuple[str, ...], *, head_check: str = HEAD):
    check = {
        "id": 70,
        "name": INTENT,
        "head_sha": head_check,
        "conclusion": "success",
        "app": {"id": e.ACTIONS_APP_ID, "slug": "github-actions"},
        "check_suite": {"id": 700},
    }
    run = {
        "id": 7,
        "run_attempt": 1,
        "check_suite_id": 700,
        "path": ".github/workflows/intent-gate.yml",
        "event": "pull_request",
        "head_sha": head_check,
        "head_branch": "x",
        "repository": {"full_name": REPO},
        "pull_requests": [
            {"number": 1, "head": {"sha": head_check}, "base": {"sha": BASE}}
        ],
    }

    def fake(*args: str) -> str:
        joined = " ".join(args)
        if args[:2] == ("pr", "diff"):
            return diff(*paths)
        if "/files" in joined:
            return "\n".join(json.dumps({"filename": p}) for p in paths)
        if "/check-runs" in joined:
            return json.dumps(check)
        if "/actions/runs" in joined:
            return json.dumps(run)
        if "/contents/" in joined:
            raise shadow.subprocess.CalledProcessError(1, "gh")
        if joined.endswith("/pulls/1"):
            return json.dumps({"head": {"sha": HEAD}, "base": {"sha": BASE}})
        raise AssertionError(f"unexpected gh call: {joined}")

    return fake


def decide(paths: tuple[str, ...], **kwargs):
    shadow._gh = provider(paths, **kwargs)
    return shadow.m.decide(shadow.inputs(REPO, 1, DELEGATION))


def codes(result) -> list[str]:
    return [r.code for r in result.reasons]


def main() -> int:
    gate.configure(*gate.load_scope(ROOT / shadow.POLICY))

    # A delegated decision record with genuine, current evidence: AUTHORIZE (shadow only).
    ok = decide(("docs/decisions/0009-x.md",))
    assert (ok.outcome, codes(ok)) == ("AUTHORIZE", []), codes(ok)
    assert ok.subject == e.Subject(REPO, HEAD, BASE, POLICY)

    # The same evidence for an older head is refused by name (D-21).
    stale = decide(("docs/decisions/0009-x.md",), head_check="c" * 40)
    assert (stale.outcome, codes(stale)) == (
        "VERIFY",
        ["EVIDENCE_NOT_APPLICABLE:intent-gate"],
    ), codes(stale)

    # The engine, agent instructions and unknown files escalate whatever else is delegated.
    mixed = decide(
        (
            "docs/decisions/0009-x.md",
            "mandate/src/mandate/gate.py",
            "AGENTS.md",
            "app/main.py",
        )
    )
    assert mixed.outcome == "ESCALATE", codes(mixed)
    assert {
        "RESERVED:merge-authority",
        "RESERVED:agent-instructions",
        "UNCLASSIFIED",
    } <= set(codes(mixed)), codes(mixed)

    # Findings attach to exact paths: a name contained in another path gains nothing from it.
    nested = decide(("docs/decisions/README.md", "README.md"))
    assert ("unclassified", "README.md") in shadow.findings(
        diff("docs/decisions/README.md", "README.md"),
        ["docs/decisions/README.md", "README.md"],
        DELEGATION,
        lambda _p: None,
    )
    assert nested.outcome == "ESCALATE" and "UNCLASSIFIED" in codes(nested), codes(
        nested
    )

    # A renamed reserved file still counts under its old name.
    renamed = "diff --git a/docs/AGENTS.md b/docs/decisions/0010-x.md\nsimilarity index 100%\nrename from docs/AGENTS.md\nrename to docs/decisions/0010-x.md\n"
    moved = shadow.findings(renamed, ["docs/decisions/0010-x.md"], DELEGATION, lambda _p: None)
    assert ("agent-instructions", "docs/AGENTS.md") in moved, moved

    # A file's own diff decides its findings, and a file missing from the API's
    # file list still counts (fail closed).
    original = gate.scope_findings
    gate.scope_findings = lambda chunk: (
        [("credential", "adds a secret")] if "secret.yml" in chunk else []
    )
    try:
        found = shadow.findings(
            diff("docs/decisions/0009-x.md", "secret.yml"),
            ["docs/decisions/0009-x.md"],
            DELEGATION,
            lambda _p: None,
        )
    finally:
        gate.scope_findings = original
    assert ("credential", "secret.yml") in found and (
        "credential",
        "docs/decisions/0009-x.md",
    ) not in found, found

    # The summary states that shadow grants nothing.
    assert "grants nothing" in shadow.summary(
        1, mixed
    ) and "ESCALATE" in shadow.summary(1, mixed)

    print("shadow tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
