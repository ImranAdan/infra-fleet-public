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
| Applicability | Repository, head, base or delegation source differ from the subject | `EVIDENCE_NOT_APPLICABLE:<name>` (VERIFY, D-21) if only genuine evidence about another subject remains; the detail names the check runs and mismatched fields |
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

## Ledger

`mandate.ledger` keeps receipts on a protected branch (KAN-4 page 09, D-20).
The layout is immutable `v1/receipts/<decision_id>/<revision>.json` files plus
a hash-chained `v1/ledger.jsonl`.

- **Append:** `append()` is a compare-and-swap. It makes one commit whose only
  parent is the tip it read, then does a non-force ref update. A concurrent
  writer is refused and retries.
- **Retries and collisions:** an identical retry appends nothing. Different
  bytes at one revision give `RECEIPT_COLLISION`.
- **Failures:** a broken chain gives `LEDGER_INVALID`. An exhausted race or a
  provider error gives `LEDGER_UNAVAILABLE`.
- **Verify:** `verify()` catches middle deletion on its own. It catches tail
  truncation and full rewrite only while an anchor (merge trailer, unexpired
  check or owner copy) still names a later head.
- **Topology check:** `python3 -m mandate.ledger rulesets <repo> <ref> <app>`
  checks the two-ruleset layout read-only.

The live drill is in `drill/ledger/README.md`.

## Receipts

`mandate.receipt` turns a `Decision` into a versioned receipt and records it
through `ledger.append()` (KAN-26).

- **Decision ID:** `d-` plus the SHA-256 of the canonical subject. The subject
  is the repository, pull request, head, base, delegation revision and
  enforcement snapshot, so any drift gives a new ID.
- **Revisions:** `record()` appends `r1`, `r2` and so on under one ID. It
  appends only when the latest revision says something different, ignoring the
  clock. Rerunning identical inputs is a no-op. Flipping back to an earlier
  result is a new revision, never a reuse. A concurrent writer that takes the
  same revision makes it re-read and take the next.
- **Check run:** `reconcile_check(decision_id, app_id=…)` is the only
  publisher. The caller names a decision, never a revision. It reads the
  verified ledger and makes every `mandate/decision` run *created by the
  publisher App* for that decision show the latest revision; another App's run
  with the same name is never touched. It writes nothing when that is already
  shown. The conclusion comes from the receipt's recorded enforcement, never a
  caller flag. Only a live `sha256:` snapshot can pass, a shadow receipt is
  always `neutral`, and any other value fails. The summary is capped at
  65,535 UTF-8 bytes, cut on a character boundary.
- **One writer per pull request:** GitHub's ruleset reads the check's
  conclusion, and the Checks API has no compare-and-swap. So every job that
  records receipts or writes checks must run in the one canonical group,
  `mandate-decision-${{ github.repository }}-${{ inputs.pr }}`, with
  `cancel-in-progress: false`. That means writers are workflows called with a
  `pr` input, so every caller computes the same group.
  `serial_violations()` checks this per job over `.github/workflows/` in the
  tests, and fails closed on a workflow it can't parse. A job counts as a
  writer if it:
  - uses `mandate.receipt`;
  - grants `checks: write` or `write-all`;
  - mints an App token with `permission-checks: write`;
  - mints an App token with no `permission-*` inputs at all, because that
    token carries all of the App's permissions, and the Mandate App has
    `checks: write`.

  Jobs that declare no permissions get the repository default, which is
  `read` (`gh api repos/ImranAdan/infra-fleet-public/actions/permissions/workflow`
  → `"default_workflow_permissions":"read"`). Changing that default to
  `write` would bypass this check.
  - **Why it's safe:** GitHub runs at most one job in a group at a time. A
    newer pending run replaces an older pending one, and because it
    reconciles from the ledger, it loses nothing.
  - **Backstop:** if the ledger still moves during a reconcile (only possible
    when the boundary is bypassed), the reconcile re-reads and shows the newer
    revision before returning. It lists every run for the decision
    (`filter=all`, paged), so duplicates from a past race are kept current.
- **Merge trailers:** `trailers()` gives `Mandate-Decision`,
  `Mandate-Receipt-Digest` and `Mandate-Chain-Head` after final revalidation.
  The fresh decision must be about the subject the merge worker acted on, must
  have a live enforcement snapshot (a `sha256:` digest; shadow grants
  nothing) and must AUTHORIZE. Otherwise it refuses with `HEAD_CHANGED`, `BASE_CHANGED`,
  `ENFORCEMENT_DRIFT` or `CONTRACT_ERROR`. It then records that decision,
  which is a no-op when it is already the latest revision, so the trailers
  always name the latest revision. A stale worker holding a superseded
  AUTHORIZE can't anchor a merge to it.
- **Audit:** `audit()` checks a ledger offline against merge-commit anchors.
  It reports middle deletion, tail truncation, full rewrite and an anchor whose
  receipt isn't recorded at or before its chain head.
- **Limits:** forged appends with a stolen key, or truncation after the last
  anchor, are reported as "not detectable with available anchor". This
  happens every time, even when the anchor is the visible tip, because a
  truncated tail would look the same. The anchor
  is repository-local, not an independent transparency log.

The shadow output includes the receipt it would record. Nothing writes a
production ledger yet: that needs the `mandate-ledger` branch, its two
rulesets and a `checks: write` token, all owner actions gated by KAN-31.

## Shadow decisions

`mandate.shadow` turns one live pull request into a `DecisionInput` and runs
`decide()` on it (the KAN-27 adapter; D-23: it adds no outcome or reason). The
input is built from:

- **Findings:** the engine classifies each file from its own diff, plus
  reserved surfaces read at the trusted base. A file that appears in the diff
  but not in the API's file list still counts.
- **Evidence:** the head's check runs, each correlated to its workflow run.
- **Policy:** the owner's delegation at a pinned commit.

Facts such as permission deltas aren't computed yet, so classes that need them
never match. Mechanical refusals belong to the executor (KAN-28).

`.github/workflows/mandate-shadow.yml` runs it from the default branch after
each Intent Gate run (not the retarget variant, whose producer no class
requires yet). It writes the outcome to the job summary and a
`decision.json` artifact. It reads only and grants nothing.

```bash
PYTHONPATH=mandate/src python3 -m mandate.shadow ImranAdan/infra-fleet-public 222 \
  --delegation-sha da6db52b465c99d955e07809bdf135104db3bc7f
```

Test it through the entry point, the way the merge worker runs it:

```bash
python3 .claude/skills/merge-gate/merge_ready.py --self-test
python3 .claude/skills/merge-gate/judge.py --self-test
python3 mandate/tests/test_delegation.py
python3 mandate/tests/test_evidence.py
python3 mandate/tests/test_decision.py
python3 mandate/tests/test_shadow.py
python3 mandate/tests/test_ledger.py
python3 mandate/tests/test_receipt.py
```
