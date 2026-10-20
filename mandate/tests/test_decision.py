"""Decision checks (KAN-24). Run: python3 mandate/tests/test_decision.py

A truth table through the real decide(): every outcome, every precedence edge,
and at least one literal fixture per registered reason code.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from mandate import decision as m  # noqa: E402
from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402

REPO = "ImranAdan/infra-fleet-public"
HEAD, BASE = "a" * 40, "b" * 40
POLICY = f"{d.DELEGATION_REPOSITORY}@{'d' * 40}:repositories/infra-fleet-public.toml"
DELEGATION = d.parse((HERE.parent / "examples" / "infra-fleet-public.toml").read_text(), REPO, POLICY)
SUBJECT = e.Subject(repository=REPO, head_sha=HEAD, base_sha=BASE, policy=POLICY)
INTENT = "Intent gate / Declared intent"


def record(conclusion: str | None = "success", *, workflow: str = ".github/workflows/intent-gate.yml",
           run_id: int = 7, check_id: int = 70) -> e.EvidenceRecord:
    return e.normalize(
        {
            "id": check_id, "name": INTENT, "head_sha": HEAD, "conclusion": conclusion,
            "app": {"id": e.ACTIONS_APP_ID, "slug": "github-actions"}, "check_suite": {"id": run_id * 10},
        },
        {
            "id": run_id, "run_attempt": 1, "check_suite_id": run_id * 10, "path": workflow,
            "event": "pull_request", "head_sha": HEAD, "head_branch": "x",
            "repository": {"full_name": REPO},
            "pull_requests": [{"number": 1, "head": {"sha": HEAD}, "base": {"sha": BASE}}],
        },
        SUBJECT,
    )


GREEN = record()
DOCS = (("decision-record", "docs/decisions/0009-x.md"),)


def decide(findings=DOCS, records=(GREEN,), *, delegation=DELEGATION, facts=None, blocking=()):
    return m.decide(
        m.DecisionInput(
            delegation=delegation,
            subject=SUBJECT,
            findings=tuple(findings),
            facts=facts or {},
            records=tuple(records),
            blocking=tuple(blocking),
        )
    )


def outcome(**kwargs) -> tuple[str, list[str]]:
    result = decide(**kwargs)
    return result.outcome, [r.code for r in result.reasons]


def main() -> int:
    # AUTHORIZE only when every finding is delegated and its evidence holds.
    assert outcome() == ("AUTHORIZE", []), outcome()
    authorized = decide()
    assert authorized.classes == ("decision-prose",) and authorized.accepted[0][0] == "intent-gate"

    # VERIFY: obtainable proof is missing or still running.
    assert outcome(records=()) == ("VERIFY", ["EVIDENCE_REQUIRED:intent-gate"])
    assert outcome(records=(record(None),)) == ("VERIFY", ["EVIDENCE_PENDING:intent-gate"])

    # BLOCK: forged, conflicting or failed proof, and mechanical refusals.
    forged = record(workflow=".github/workflows/forged.yml", run_id=8, check_id=80)
    assert outcome(records=(GREEN, forged)) == ("BLOCK", ["CHECK_WRONG_SOURCE"])
    assert outcome(records=(GREEN, record("failure", run_id=9, check_id=90))) == ("BLOCK", ["EVIDENCE_CONFLICT"])
    assert outcome(records=(record("failure"),)) == ("BLOCK", ["EVIDENCE_FAILED:intent-gate"])
    for code in ("HEAD_CHANGED", "BASE_CHANGED", "CHECKS_FAILED", "REVIEW_UNRESOLVED",
                 "ENFORCEMENT_MISSING", "ENFORCEMENT_DRIFT", "RECEIPT_COLLISION",
                 "LEDGER_INVALID", "LEDGER_UNAVAILABLE"):
        assert outcome(blocking=(code,)) == ("BLOCK", [code]), code
    # An unregistered mechanical code is a contract error, never ignored.
    assert outcome(blocking=("LOOKS_FINE",)) == ("BLOCK", ["CONTRACT_ERROR"])

    # ESCALATE: reserved, undelegated or unclassified authority, delegated escalation.
    assert outcome(findings=(("merge-authority", "mandate/x.py"),)) == ("ESCALATE", ["RESERVED:merge-authority"])
    assert outcome(findings=(("agent-instructions", "AGENTS.md"),)) == ("ESCALATE", ["RESERVED:agent-instructions"])
    assert outcome(findings=(("admission-policy", "k8s/p/policies/x.yaml"),)) == ("ESCALATE", ["UNDELEGATED:admission-policy"])
    assert outcome(findings=(("unclassified", "app/main.py"),)) == ("ESCALATE", ["UNCLASSIFIED"])
    assert outcome(findings=(("made-up", "x"),)) == ("ESCALATE", ["UNCLASSIFIED"])
    assert outcome(findings=()) == ("ESCALATE", ["UNCLASSIFIED"])
    # A class whose facts are not proven does not match, so it fails closed.
    workflow = (("workflow", ".github/workflows/lint.yml"),)
    assert outcome(findings=workflow) == ("ESCALATE", ["UNDELEGATED:workflow"])
    proven = {"permission_delta": "none", "secret_delta": "none", "trigger_delta": "none"}
    assert outcome(findings=workflow, facts=proven) == ("AUTHORIZE", [])
    assert outcome(findings=workflow, facts={**proven, "trigger_delta": "added"}) == ("ESCALATE", ["UNDELEGATED:workflow"])
    escalating = d.parse(
        (HERE.parent / "examples" / "infra-fleet-public.toml").read_text().replace(
            'id = "decision-prose"\nmatch = { category = ["decision-record", "product-requirements"] }\ndecide = "authorize"',
            'id = "decision-prose"\nmatch = { category = ["decision-record", "product-requirements"] }\ndecide = "escalate"',
        ),
        REPO,
        POLICY,
    )
    assert outcome(delegation=escalating) == ("ESCALATE", ["ESCALATE_CLASS:decision-prose"])

    # A delegation built around the loader (no declared producer) cannot authorize.
    undeclared = dataclasses.replace(DELEGATION, evidence=())
    assert outcome(delegation=undeclared) == ("BLOCK", ["EVIDENCE_UNDECLARED:intent-gate"])

    # Contract errors in the delegation fail closed with their own reasons.
    invalid = d.DelegationError("DELEGATION_INVALID", "reserved class set to authorize")
    assert outcome(delegation=invalid) == ("ESCALATE", ["DELEGATION_INVALID"])
    collision = d.DelegationError("IDENTITY_COLLISION", "owner listed as agent")
    assert outcome(delegation=collision) == ("ESCALATE", ["IDENTITY_COLLISION"])
    assert outcome(delegation=d.DelegationError("SOMETHING_ELSE", "x")) == ("ESCALATE", ["DELEGATION_INVALID"])
    # Shadow mode loads an owner-as-agent delegation, but it never authorizes.
    shadow_collision = dataclasses.replace(DELEGATION, agents=(DELEGATION.owner,))
    assert shadow_collision.identity_collision
    assert outcome(delegation=shadow_collision) == ("ESCALATE", ["IDENTITY_COLLISION"])
    # A malformed owner path pattern is refused at load, never a crash here.
    try:
        d.parse(
            (HERE.parent / "examples" / "infra-fleet-public.toml").read_text().replace(
                "lockfile_sibling = true }", 'lockfile_sibling = true, paths = ["["] }'
            ),
            REPO,
            POLICY,
        )
    except d.DelegationError as exc:
        assert exc.code == "DELEGATION_INVALID" and "paths" in str(exc), exc
    else:
        raise AssertionError("parse accepted a malformed paths pattern")

    # Precedence: BLOCK > ESCALATE > VERIFY > AUTHORIZE, every pair and the triple.
    block = {"blocking": ("HEAD_CHANGED",)}
    reserved = {"findings": DOCS + (("credential", ".github/workflows/x.yml"),)}
    missing = {"records": ()}
    assert outcome(**block, **reserved)[0] == "BLOCK"
    assert outcome(**block, **missing)[0] == "BLOCK"
    assert outcome(**reserved, **missing)[0] == "ESCALATE"
    assert outcome(**block, **reserved, **missing) == (
        "BLOCK", ["HEAD_CHANGED", "RESERVED:credential", "EVIDENCE_REQUIRED:intent-gate"]
    )
    for a, b in itertools.permutations(m.OUTCOMES, 2):
        assert m.worst([a, b]) == (a if m.OUTCOMES.index(a) < m.OUTCOMES.index(b) else b)

    # Every registered code has a literal fixture above; every reason carries
    # its registry entry, and an unregistered code is refused.
    for code in m.REGISTRY:
        assert code in Path(__file__).read_text(), f"no fixture for {code}"
    try:
        m.reason("NOT_A_CODE")
    except ValueError:
        pass
    else:
        raise AssertionError("reason() accepted an unregistered code")

    # Deterministic: one snapshot, one outcome and reason set, whatever the order.
    shuffled = decide(findings=tuple(reversed(reserved["findings"])), records=(), blocking=("HEAD_CHANGED",))
    assert shuffled == decide(**block, **reserved, **missing)

    # Serializable into a DecisionRecord without interpretation.
    data = json.loads(json.dumps(decide(**block, **reserved, **missing).to_dict(), sort_keys=True))
    assert data["outcome"] == "BLOCK" and data["registry_version"] == m.REGISTRY_VERSION
    assert data["reasons"][0] == {"code": "HEAD_CHANGED", "outcome": "BLOCK", "owner": "mandate", "detail": ""}
    assert data["policy"] == POLICY and data["subject"]["head_sha"] == HEAD
    assert e.EvidenceRecord.from_dict(json.loads(json.dumps(authorized.to_dict()))["accepted"][0]["records"][0]) == GREEN

    # Legacy verdicts never map to AUTHORIZE; READY must be recomputed.
    assert m.LEGACY == {"READY": None, "PARK": "ESCALATE", "JUDGE": "ESCALATE", "BLOCKED": "BLOCK"}
    assert "AUTHORIZE" not in m.LEGACY.values()

    print("decision tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
