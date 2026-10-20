# Mandate decision engine

`mandate.gate` decides whether an agent-authored pull request may merge:
`READY`, `PARK` (the owner decides), `JUDGE` or `BLOCKED`. It is one
implementation shared by every governed repository, with no third-party
dependencies.

A repository binds the engine to its own rules through a thin entry point that
calls `gate.cli(argv, policy_path, self_test)`. In this repository that is
`.claude/skills/merge-gate/merge_ready.py`, and its rules are
`.claude/skills/merge-gate/decision-policy.toml`. The per-repository settings
in that policy are:

| Setting | Meaning |
|---|---|
| `[scope] merge_authority` | `^`-anchored path patterns whose change is merge authority (the owner decides) |
| `[dependabot] version_only` | Whether verified, signed, version-only Dependabot bumps may be decided by evidence |
| `[[rule]]`, `[evidence]` | Deciders per category, and the declared-intent checks traced to their workflows |

The engine fails closed: until a repository's policy is loaded, every changed
path counts as merge authority, and an invalid policy parks the pull request.

Everything under `mandate/` is always merge authority: `configure()` adds
`^mandate/` itself, whatever a repository's policy lists, so an agent cannot
edit the code that judges its own changes.

## Delegation

`mandate.delegation` loads the owner's delegation for one repository: what
Mandate may authorize, which evidence each class needs, and what always
escalates. It lives in the owner-only repository
[`ImranAdan/mandate-delegation`](https://github.com/ImranAdan/mandate-delegation)
at `repositories/<repository-name>.toml` and is read at a full commit SHA
(`fetch`); a branch name or short SHA is refused. The loader is strict and
fails closed with `DELEGATION_INVALID`: unknown keys, unknown categories,
evidence a class requires but nobody declares, authorizing without evidence,
and any class that authorizes a reserved category (credentials, widened
permissions, IAM, permanent infrastructure, migrations, merge authority, the
delegation itself, enforcement, declared intent, evidence producers, agent
instructions). Operational `admission-policy` is delegable; constitutional
`intent-policy` is not. `reserved_findings(delegation, paths, read)` reports the
reserved surfaces by path alone (`intent/`, rulesets, `CODEOWNERS`, the engine
under `mandate/`, any `AGENTS.md` or `CLAUDE.md`, and this delegation's
evidence-producer workflows together with every local workflow or action they
call (including repository scripts they run), followed through `read` at the
trusted base), so no owner class or class
order can authorize them. The engine reports `policies/` and `k8s/*/policies/`
as `admission-policy`; Fleet's decision policy still sends it to the owner. An owner listed as an agent is refused in
`enforce` mode and escalates every shadow decision (`IDENTITY_COLLISION`).
A malformed `match.paths` pattern fails the load. `examples/infra-fleet-public.toml` is
Fleet's delegation.

Two producers may not claim the same check name.

## Evidence

`mandate.evidence` turns a GitHub check run and the workflow run behind it
into an `EvidenceRecord` (`normalize`) that keeps the provider IDs (check run,
suite, workflow run and attempt, App), the workflow path and event, and the
exact subject: repository, head, base and delegation source. `to_dict` /
`from_dict` round-trip it for receipts. `evaluate(delegation, require,
records, subject)` judges a class's required evidence on three independent
axes and returns typed failures, never an outcome:

| Axis | Fails when | Failure |
| --- | --- | --- |
| Authenticity | The check name matches but the App, workflow path, event or dispatch branch is not the declared producer's | `CHECK_WRONG_SOURCE` |
| Applicability | Repository, head, base or delegation source differ from the subject | `EVIDENCE_REQUIRED:<name>` if nothing current remains |
| Sufficiency | The required producer is absent, running, failed, or reports conflicting or unattributable results | `EVIDENCE_REQUIRED`, `EVIDENCE_PENDING`, `EVIDENCE_FAILED:<name>`, `EVIDENCE_CONFLICT` |

A rerun supersedes earlier attempts of the same workflow run; every result of
the latest attempt counts. Green checks the
class does not require carry no weight, and PR prose is not an input. Outcome
precedence and the public reason codes are the decision's (KAN-24).

## Decision

`mandate.decision.decide(DecisionInput)` is a pure function from one snapshot
(delegation or its load error, subject, `(category, path)` findings, proven PR
facts, evidence records, and the caller's mechanical refusals) to
`AUTHORIZE | VERIFY | BLOCK | ESCALATE` with every reason. Precedence is
BLOCK > ESCALATE > VERIFY > AUTHORIZE, and AUTHORIZE needs no reason at all:
every finding matched to an authorizing class, with its required evidence
accepted by `mandate.evidence`. Reasons come only from the versioned
`REGISTRY` (code, outcome, who acts next); an unregistered mechanical code is a
`CONTRACT_ERROR`. A path with no category is `UNCLASSIFIED`, and a class match
key the caller has not proven never matches, so both escalate. No model text is
an input. `Decision.to_dict()` is the DecisionRecord payload.

Fleet's live gate still decides `READY`/`PARK`. `LEGACY` maps its verdicts
(`PARK`/`JUDGE` → ESCALATE, `BLOCKED` → BLOCK, `READY` → recompute), and none
maps to AUTHORIZE.

Test it through the entry point, the way the merge worker runs it:

```bash
python3 .claude/skills/merge-gate/merge_ready.py --self-test
python3 .claude/skills/merge-gate/judge.py --self-test
python3 mandate/tests/test_delegation.py
python3 mandate/tests/test_evidence.py
python3 mandate/tests/test_decision.py
```
