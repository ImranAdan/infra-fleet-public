"""Delegation loader checks. Run: python3 mandate/tests/test_delegation.py"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import delegation as d  # noqa: E402

REPO = "ImranAdan/infra-fleet-public"
SOURCE = f"{d.DELEGATION_REPOSITORY}@{'a' * 40}:repositories/infra-fleet-public.toml"
MINIMAL = """
version = 1
repository = "ImranAdan/infra-fleet-public"
mode = "shadow"
owner = "ImranAdan"
agents = []
[evidence.ci]
check = "CI"
workflow = ".github/workflows/ci.yml"
event = "pull_request"
[[classes]]
id = "docs"
match = { category = "decision-record" }
decide = "authorize"
require = ["ci"]
"""


def rejects(text: str, code: str = "DELEGATION_INVALID", expect: str = "") -> None:
    try:
        d.parse(text, REPO, SOURCE)
    except d.DelegationError as exc:
        assert exc.code == code, exc
        assert expect in str(exc), (expect, str(exc))
        return
    raise AssertionError(f"accepted a delegation that should fail with {code}: {expect}")


def main() -> int:
    # Minimal and full examples load and keep their meaning.
    minimal = d.parse(MINIMAL, REPO, SOURCE)
    assert minimal.mode == "shadow" and minimal.owner == "ImranAdan" and minimal.agents == ()
    assert minimal.classes[0].require == ("ci",) and minimal.source == SOURCE
    full = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text(), REPO, SOURCE)
    assert [c.id for c in full.classes][-1] == "reserved"
    assert full.classes[-1].decide == "escalate" and "merge-authority" in full.classes[-1].categories
    assert dict(full.classes[1].match) == {"lockfile_sibling": True}

    # Unknown keys and bad values fail closed.
    rejects(MINIMAL + "surprise = true\n", expect="unknown keys: surprise")
    rejects(MINIMAL.replace('decide = "authorize"', 'decide = "allow"'), expect="decide")
    rejects(MINIMAL.replace('mode = "shadow"', 'mode = "auto"'), expect="mode")
    rejects(MINIMAL.replace("version = 1", "version = 2"), expect="version")
    rejects(MINIMAL.replace('event = "pull_request"', 'event = "pull_request_target"'), expect="event")
    rejects(MINIMAL.replace('category = "decision-record"', 'category = "docs"'), expect="unknown categories")
    rejects(MINIMAL.replace('match = { category = "decision-record" }', 'match = { category = "decision-record", magic = 1 }'), expect="unknown keys: magic")
    rejects("version = 1\n[[", expect="not valid TOML")

    # A file for another repository cannot govern this one.
    rejects(MINIMAL.replace(REPO, "ImranAdan/other"), expect="not 'ImranAdan/infra-fleet-public'")

    # A-13: a class that authorizes a reserved category invalidates the whole file.
    for reserved in sorted(d.RESERVED):
        rejects(MINIMAL.replace('"decision-record"', f'"{reserved}"'), expect=f"reserved: {reserved}")
    # Escalating a reserved category is fine.
    d.parse(MINIMAL.replace('"decision-record"', '"credential"').replace('"authorize"', '"escalate"'), REPO, SOURCE)

    # Authorization needs declared evidence.
    rejects(MINIMAL.replace('require = ["ci"]', 'require = ["tests"]'), expect="declared evidence")
    rejects(MINIMAL.replace('require = ["ci"]\n', ""), expect="without requiring any evidence")

    # Recovery is metadata from a fixed set; it grants nothing.
    rejects(MINIMAL + 'recovery = "R9"\n', expect="recovery")

    # Owner listed as an agent: tolerated in shadow, refused in enforce.
    collide = MINIMAL.replace("agents = []", 'agents = ["imranadan"]')
    assert d.parse(collide, REPO, SOURCE).identity_collision
    rejects(collide.replace('mode = "shadow"', 'mode = "enforce"'), code="IDENTITY_COLLISION", expect="owner")

    # Mutable references are refused before any network call.
    for ref in ("main", "HEAD", "a" * 39, "A" * 40):
        try:
            d.fetch(REPO, ref)
        except d.DelegationError as exc:
            assert "full commit SHA" in str(exc), exc
        else:
            raise AssertionError(f"fetch accepted mutable ref {ref!r}")

    # A-19: a delegation change after evidence is drift, so the decision is redone.
    newer = d.parse(MINIMAL, REPO, SOURCE.replace("a" * 40, "b" * 40))
    assert d.drifted(minimal, newer) and not d.drifted(minimal, d.parse(MINIMAL, REPO, SOURCE))
    assert d.path_for(REPO) == "repositories/infra-fleet-public.toml"

    print("delegation tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
