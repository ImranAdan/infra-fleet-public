"""Shadow adapter checks. Run: python3 mandate/tests/test_shadow.py

Provider responses are canned and shaped like the REST API; the adapter and
decide() are the real code. Nothing here calls GitHub.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
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


def provider(paths: tuple[str, ...], *, head_check: str = HEAD, files=None, requested=None):
    """Canned REST responses. ``files`` maps (ref, path) to text; the server
    decodes a contents path, so ``%41`` names ``A``. ``requested`` collects
    each contents URL asked for."""
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
            url = next(a for a in args if "/contents/" in a)
            (requested if requested is not None else []).append(url)
            path, _, query = url.split("/contents/", 1)[1].partition("?")
            text = (files or {}).get((query.removeprefix("ref="), urllib.parse.unquote(path)))
            if text is None:
                raise subprocess.CalledProcessError(1, "gh")
            return text
        if joined.endswith("/pulls/1"):
            return json.dumps({"head": {"sha": HEAD}, "base": {"sha": BASE}})
        raise AssertionError(f"unexpected gh call: {joined}")

    return fake


def snapshot(paths: tuple[str, ...], **kwargs):
    gate.gh = provider(paths, **kwargs)
    return shadow.inputs(REPO, 1, DELEGATION)


def decide(paths: tuple[str, ...], **kwargs):
    return shadow.m.decide(snapshot(paths, **kwargs))


def codes(result) -> list[str]:
    return [r.code for r in result.reasons]


def main() -> int:
    gate.configure(*gate.load_scope(ROOT / shadow.POLICY))

    # A delegated decision record with genuine, current evidence: AUTHORIZE (shadow only).
    ok = decide(("docs/decisions/0009-x.md",))
    assert (ok.outcome, codes(ok)) == ("AUTHORIZE", []), codes(ok)
    assert ok.subject == e.Subject(REPO, HEAD, BASE, POLICY)

    # The same evidence for an older head is refused by name.
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
    moved = shadow.findings(
        renamed, ["docs/decisions/0010-x.md"], DELEGATION, lambda _p: None
    )
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

    # Revision reads quote the path: a workflow named x%41.yml is read as itself,
    # not as xA.yml, a benign file the same PR may add. Only the parsed
    # comparison sees the trigger, since the canned diff shows no workflow text.
    quiet = "on: pull_request\njobs: {}\n"
    loud = "on: pull_request_target\npermissions: write-all\njobs: {}\n"
    odd, benign = ".github/workflows/x%41.yml", ".github/workflows/xA.yml"
    files = {(BASE, odd): quiet, (HEAD, odd): loud, (BASE, benign): quiet, (HEAD, benign): quiet}
    requested: list[str] = []
    quoted = decide((odd,), files=files, requested=requested)
    want = f"repos/{REPO}/contents/.github/workflows/x%2541.yml"
    assert requested[:2] == [f"{want}?ref={BASE}", f"{want}?ref={HEAD}"], requested
    assert (quoted.outcome, "RESERVED:merge-authority" in codes(quoted)) == ("ESCALATE", True), codes(quoted)

    # lockfile_sibling, the dependency-manifest class's one fact, is proven from
    # the change's own files read at the exact head; whatever is unproven refuses.
    lh = "applications/load-harness/"
    pinned = "gitlint-core==0.19.1\nsh==2.4.0\n"  # Fleet #166's requirements-dev.txt
    runtime = "attrs==26.1.0             # via jsonschema\nflask==3.1.2 \\\n    --hash=sha256:" + "0" * 64 + "\n"
    dev = "# Test dependencies\n-r requirements.txt\npytest==9.1.1\n"

    def manifest(paths, head, base=None):
        """(facts, outcome, codes) for a change whose files read as ``head`` at
        the head commit and ``base`` at the base commit."""
        files = {(HEAD, k): v for k, v in head.items()} | {(BASE, k): v for k, v in (base or {}).items()}
        requested: list[str] = []
        snap = snapshot(paths, files=files, requested=requested)
        result = shadow.m.decide(snap)
        manifest.requested = requested
        return snap.facts, result.outcome, codes(result)

    resolved = ({"lockfile_sibling": True}, "AUTHORIZE", [])
    refused = ({"lockfile_sibling": False}, "ESCALATE", ["UNDELEGATED:dependency-manifest"])
    cases = {
        "a pinned requirements file": (("requirements-dev.txt",), {"requirements-dev.txt": pinned}, None, resolved),
        "a manifest with its lockfile": ((lh + "package.json", lh + "package-lock.json"),
                                         {lh + "package.json": "{}", lh + "package-lock.json": "{}"}, None, resolved),
        "an include pinned at head": ((lh + "requirements-dev.txt",),
                                      {lh + "requirements-dev.txt": dev, lh + "requirements.txt": runtime}, None, resolved),
        "includes in a cycle": (("requirements-a.txt",), {"requirements-a.txt": "-r requirements-b.txt\n",
                                "requirements-b.txt": "-r requirements-a.txt\nx==1\n"}, None, resolved),
        "a lockfile alone": (("applications/x/uv.lock",), {"applications/x/uv.lock": "version = 1\n"}, None, resolved),
        "a manifest without its lockfile": ((lh + "package.json",), {lh + "package.json": "{}"}, None, refused),
        "a lockfile changed in another directory": ((lh + "package.json", "applications/x/package-lock.json"),
                                                    {lh + "package.json": "{}", "applications/x/package-lock.json": "{}"},
                                                    None, refused),
        "a lockfile deleted beside its manifest": ((lh + "package.json", lh + "package-lock.json"),
                                                   {lh + "package.json": "{}"}, None, refused),
        "a lockfile deleted alone": (("applications/x/uv.lock",), {}, None, refused),
        "a range": (("requirements.txt",), {"requirements.txt": "requests>=2.32\n"}, None, refused),
        "a wildcard": (("requirements.txt",), {"requirements.txt": "requests==2.*\n"}, None, refused),
        "an editable source": (("requirements.txt",), {"requirements.txt": "-e git+https://example.com/x.git#egg=x\n"}, None, refused),
        "another index": (("requirements.txt",), {"requirements.txt": "--index-url https://example.com/simple\nrequests==2.32.4\n"}, None, refused),
        "an unreadable requirements file": (("requirements.txt",), {}, None, refused),
        "an include unpinned at head": ((lh + "requirements-dev.txt",),
                                        {lh + "requirements-dev.txt": dev, lh + "requirements.txt": "flask\n"}, None, refused),
        "an include outside the repository": (("requirements.txt",), {"requirements.txt": "-r ../x.txt\n", "../x.txt": "x==1\n"}, None, refused),
        "pinned at base, a range at head": (("requirements-dev.txt",), {"requirements-dev.txt": "sh>=2\n"},
                                            {"requirements-dev.txt": pinned}, refused),
    }
    for name, (paths, head, base, want) in cases.items():
        got = manifest(paths, head, base)
        assert got == want, (name, got)
    # The fact is read at the exact head commit, never the base or a branch.
    manifest(("requirements-dev.txt",), {"requirements-dev.txt": pinned})
    reads = [u for u in manifest.requested if "requirements-dev.txt" in u]
    assert reads == [f"repos/{REPO}/contents/requirements-dev.txt?ref={HEAD}"], manifest.requested
    # The same resolved change with evidence for an older head is not authorized.
    stale_bump = decide(("requirements-dev.txt",), head_check="c" * 40, files={(HEAD, "requirements-dev.txt"): pinned})
    assert (stale_bump.outcome, codes(stale_bump)) == ("VERIFY", ["EVIDENCE_NOT_APPLICABLE:intent-gate"]), codes(stale_bump)
    # A change without a dependency manifest claims no fact.
    assert snapshot(("docs/decisions/0009-x.md",)).facts == {}

    # The summary states that shadow grants nothing.
    assert "grants nothing" in shadow.summary(
        1, mixed
    ) and "ESCALATE" in shadow.summary(1, mixed)

    print("shadow tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
