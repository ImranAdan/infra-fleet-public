"""Decision: one input snapshot to AUTHORIZE, VERIFY, BLOCK or ESCALATE.

decide() is a pure, total function. Every reason it gives comes from the
versioned REGISTRY, and the outcome is the worst reason's:

    BLOCK > ESCALATE > VERIFY > AUTHORIZE

- VERIFY: proof that could still be obtained is missing or running.
- BLOCK: proof is forged, conflicting or failed, or a mechanical precondition
  (exact head, base, review, enforcement, ledger) does not hold.
- ESCALATE: the change needs authority the delegation does not grant, or
  the delegation itself is unusable.
- AUTHORIZE: only with no reason at all, which needs every finding matched to
  an authorizing class whose required evidence is authentic, applicable and
  sufficient (mandate.evidence).

There is no model input: generated text can never create AUTHORIZE. Fleet's
live gate still decides READY/PARK; LEGACY maps those verdicts here, and none
maps to AUTHORIZE, so switching the live path (G4) cannot widen it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from mandate.delegation import CATEGORIES, RESERVED, Delegation, DelegationError
from mandate.evidence import EvidenceRecord, Subject, evaluate

REGISTRY_VERSION = 1
OUTCOMES = ("BLOCK", "ESCALATE", "VERIFY", "AUTHORIZE")  # worst first

# code (before any ":<name>") -> (outcome, who acts next)
REGISTRY: dict[str, tuple[str, str]] = {
    # Evidence (mandate.evidence)
    "EVIDENCE_REQUIRED": ("VERIFY", "agent"),
    "EVIDENCE_PENDING": ("VERIFY", "mandate"),
    "CHECK_WRONG_SOURCE": ("BLOCK", "agent"),
    "EVIDENCE_CONFLICT": ("BLOCK", "agent"),
    "EVIDENCE_FAILED": ("BLOCK", "agent"),
    "EVIDENCE_UNDECLARED": ("BLOCK", "owner"),
    # Mechanical preconditions supplied by the caller
    "HEAD_CHANGED": ("BLOCK", "mandate"),
    "BASE_CHANGED": ("BLOCK", "mandate"),
    "CHECKS_FAILED": ("BLOCK", "agent"),
    "REVIEW_UNRESOLVED": ("BLOCK", "agent"),
    "ENFORCEMENT_MISSING": ("BLOCK", "owner"),
    "ENFORCEMENT_DRIFT": ("BLOCK", "mandate"),
    "RECEIPT_COLLISION": ("BLOCK", "mandate"),
    "LEDGER_INVALID": ("BLOCK", "mandate"),
    "LEDGER_UNAVAILABLE": ("BLOCK", "mandate"),
    "CONTRACT_ERROR": ("BLOCK", "owner"),
    # Authority
    "RESERVED": ("ESCALATE", "owner"),
    "UNDELEGATED": ("ESCALATE", "owner"),
    "UNCLASSIFIED": ("ESCALATE", "owner"),
    "ESCALATE_CLASS": ("ESCALATE", "owner"),
    "DELEGATION_INVALID": ("ESCALATE", "owner"),
    "IDENTITY_COLLISION": ("ESCALATE", "owner"),
}
# Codes a caller may pass as mechanical refusals; anything else is a contract error.
MECHANICAL = frozenset(
    {
        "HEAD_CHANGED",
        "BASE_CHANGED",
        "CHECKS_FAILED",
        "REVIEW_UNRESOLVED",
        "ENFORCEMENT_MISSING",
        "ENFORCEMENT_DRIFT",
        "RECEIPT_COLLISION",
        "LEDGER_INVALID",
        "LEDGER_UNAVAILABLE",
    }
)
# Fleet gate verdicts: READY must be recomputed here; nothing maps to AUTHORIZE.
LEGACY: dict[str, str | None] = {
    "READY": None,
    "PARK": "ESCALATE",
    "JUDGE": "ESCALATE",
    "BLOCKED": "BLOCK",
}


@dataclass(frozen=True)
class Reason:
    code: str
    outcome: str
    owner: str
    detail: str


@dataclass(frozen=True)
class DecisionInput:
    delegation: Delegation | DelegationError
    subject: Subject
    findings: tuple[tuple[str, str], ...]  # (category, path); an uncategorized path is "unclassified"
    facts: dict[str, Any]  # proven PR facts for class match keys (signed, permission_delta, ...)
    records: tuple[EvidenceRecord, ...]
    blocking: tuple[str, ...]  # MECHANICAL codes the caller observed


@dataclass(frozen=True)
class Decision:
    outcome: str
    reasons: tuple[Reason, ...]
    classes: tuple[str, ...]
    accepted: tuple[tuple[str, tuple[EvidenceRecord, ...]], ...]
    policy: str
    subject: Subject

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_version": REGISTRY_VERSION,
            "outcome": self.outcome,
            "reasons": [asdict(r) for r in self.reasons],
            "classes": list(self.classes),
            "accepted": [
                {"requirement": name, "records": [r.to_dict() for r in records]}
                for name, records in self.accepted
            ],
            "policy": self.policy,
            "subject": asdict(self.subject),
        }


def reason(code: str, detail: str = "") -> Reason:
    """A registered reason; an unregistered code is a programming error."""
    entry = REGISTRY.get(code.split(":", 1)[0])
    if entry is None:
        raise ValueError(f"unregistered reason code {code!r}")
    return Reason(code=code, outcome=entry[0], owner=entry[1], detail=detail)


def worst(outcomes: list[str]) -> str:
    return min(outcomes, key=OUTCOMES.index, default="AUTHORIZE")


def _matches(match: tuple[tuple[str, Any], ...], path: str, facts: dict[str, Any]) -> bool:
    """Every non-category match key must be proven; an unproven fact never matches."""
    for key, value in match:
        if key == "paths":
            if not any(re.search(pattern, path) for pattern in value):
                return False
        elif key not in facts or facts[key] != value:
            return False
    return True


def decide(snapshot: DecisionInput) -> Decision:
    """The outcome and full reason set for one snapshot, failing closed."""
    found: list[Reason] = []
    for code in snapshot.blocking:
        found.append(reason(code) if code in MECHANICAL else reason("CONTRACT_ERROR", code))

    delegation = snapshot.delegation
    classes: set[str] = set()
    accepted: tuple[tuple[str, tuple[EvidenceRecord, ...]], ...] = ()
    if isinstance(delegation, DelegationError):
        code = delegation.code if delegation.code == "IDENTITY_COLLISION" else "DELEGATION_INVALID"
        found.append(reason(code, str(delegation)))
        policy = ""
    else:
        policy = delegation.source
        required: set[str] = set()
        if not snapshot.findings:
            found.append(reason("UNCLASSIFIED", "no findings: nothing the delegation can authorize"))
        for category, path in snapshot.findings:
            if category not in CATEGORIES:
                found.append(reason("UNCLASSIFIED", path))
            elif category in RESERVED:
                found.append(reason(f"RESERVED:{category}", path))
            else:
                chosen = next(
                    (
                        c
                        for c in delegation.classes
                        if category in c.categories and _matches(c.match, path, snapshot.facts)
                    ),
                    None,
                )
                if chosen is None:
                    found.append(reason(f"UNDELEGATED:{category}", path))
                elif chosen.decide != "authorize":
                    found.append(reason(f"ESCALATE_CLASS:{chosen.id}", path))
                else:
                    classes.add(chosen.id)
                    required.update(chosen.require)
        if required:
            evaluation = evaluate(delegation, tuple(sorted(required)), list(snapshot.records), snapshot.subject)
            found.extend(reason(code, detail) for code, detail in evaluation.failures)
            accepted = evaluation.accepted

    # One reason per code, details merged, in a fixed order.
    merged: dict[str, Reason] = {}
    for r in found:
        kept = merged.get(r.code)
        details = sorted({*(kept.detail.split("; ") if kept and kept.detail else []), *([r.detail] if r.detail else [])})
        merged[r.code] = Reason(r.code, r.outcome, r.owner, "; ".join(details))
    reasons = tuple(sorted(merged.values(), key=lambda r: (OUTCOMES.index(r.outcome), r.code)))
    return Decision(
        outcome=worst([r.outcome for r in reasons]),
        reasons=reasons,
        classes=tuple(sorted(classes)),
        accepted=accepted,
        policy=policy,
        subject=snapshot.subject,
    )
