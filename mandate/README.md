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
  result is a new revision, never a reuse. Another PR's concurrent append
  makes it re-read and retry.
- **Stale decisions:** recorders run outside any concurrency group, so they
  can finish out of order. A recorder reads `pr_latest()` before the inputs it
  decides from and passes it to `record(…, after=…)`. If the PR has gained a
  receipt since, whatever its decision ID, the decision may be stale:
  `record()` refuses it with `STALE_DECISION`, and the recorder decides again.
  The check runs inside the ledger append's compare-and-swap loop (its
  `precondition`), so it holds atomically with the append. Each PR's receipts
  are therefore ordered by when their inputs were read, and a delayed
  AUTHORIZE can't land over a newer refusal. A decision that means the same
  as its latest revision is a no-op only while that revision is still the
  PR's latest; otherwise it passes the staleness check like any other.
  `trailers()` takes the same `after`, so a stale merge worker gets no
  trailers. The check reads receipts through the same validation as
  reconciliation, so a malformed or rebound receipt fails it closed
  (`LEDGER_INVALID`) rather than being skipped.
- **Check run:** `reconcile_check(head_sha, app_id=…)` is the only publisher.
  The caller names a head commit, never a decision or revision. It shows the
  newest decision recorded for that head on every run of the publisher App,
  replacing an older decision ID for the same head. Runs from other Apps are
  never touched, and it writes nothing when the decision is already shown.
  - **Required check:** `mandate/decision` follows the newest decision of any
    mode. Only a live `sha256:` snapshot with AUTHORIZE can pass; any other
    value fails.
  - **Shadow check:** shadow decisions show on `mandate/shadow`, never the
    required name, because GitHub counts `neutral` as passing a required
    check. A shadow decision that supersedes a live one fails the existing
    required check run, and a head with only shadow decisions gets no required check run.
  - **Shared head:** a check belongs to a commit, so it is shared by every PR
    GitHub lists as open with that commit as its current `head.sha`, whether
    or not Mandate has decided it. GitHub's commit-to-PR list includes PRs
    that have moved on, which is why the head is checked.
    - **More than one such PR:** the check fails closed, even if only one of
      them has a decision.
    - **Only one:** it shows that PR's decision on this commit, if that is
      still its latest. Otherwise nothing is current and the check fails
      closed.
    - **PR state changes:** these happen outside the writer group, so the
      reconcile re-reads PR state before returning. The live workflow
      (KAN-28) must also run on PR open, reopen and close events.
    - **Title:** gives the count (limited to 255 characters); the summary
      lists the PRs.
  - **Summary:** capped at 65,535 UTF-8 bytes, cut on a character boundary.
  - **Index binding:** each receipt's decision ID, revision, subject digest
    and outcome must equal its index entry's, so an old receipt re-appended
    under another entry gives `LEDGER_INVALID`.
  - **Other receipts:** receipts of another schema in the same ledger (the
    drill's) are skipped. A receipt that claims this schema gives
    `LEDGER_INVALID` if it lacks a field reconciliation reads, or if it isn't
    one `decide()` could produce: unregistered reasons, an outcome other than
    the worst of its reasons, an identity that isn't its subject's (the ID
    and digest must recompute from the subject, and the decision inside must
    be about the same head, base and policy), or anything but exactly schema
    v1. Schema v1 means every key `build()` emits, no other key, and the
    supported registry version.
  - **AUTHORIZE holds under its delegation:** `record(…, delegation)`,
    `trailers(…, delegation)` and `reconcile_check(…, delegations=resolver)`
    accept an AUTHORIZE only if it checks out against the pinned delegation
    its policy names.
    - A live AUTHORIZE needs a delegation in `enforce` mode; `shadow` mode
      grants no merge authority.
    - Its classes must be that delegation's authorizing classes.
    - The accepted requirements must be exactly what those classes require.
    - Re-running the production evidence rules (`evidence.evaluate`:
      producer, App, workflow, event, subject binding) on the claimed records
      must accept exactly them.

    `record()` refuses a receipt that fails any of these checks, or the exact
    schema, as `CONTRACT_ERROR`. Evidence records must match their declared
    field types exactly (`EvidenceRecord.from_dict`).

    Two facts are left to the trusted collector, which `record()` can't
    reject:
    - whether the classes should have matched the PR's findings, which
      needs the inputs (historical replay, KAN-27);
    - whether the cited check runs exist, which rests on the producer's word,
      as in `decide()`.

    G4's live collector and executor must gather real GitHub facts,
    recompute the decision from the actual PR changes, and revalidate before
    merge.
  - **Fail closed:** if anything stops the reconcile showing the current
    decision (an unreadable ledger or receipt, a provider error, nothing
    recorded for the head, anything unexpected), every existing required check run
    on the head fails first, so an earlier success never outlives it.
  - **Identifiers:** snapshots, receipt IDs, delegation names and commit
    SHAs are matched whole (`fullmatch`), so a trailing newline never
    passes.
- **One publisher per head commit; recorders outside the group:** GitHub's
  ruleset reads the check's conclusion, and the Checks API has no
  compare-and-swap. So every job that can write checks must run in the one
  canonical group,
  `mandate-decision-${{ github.repository }}-${{ inputs.head_sha }}`, with
  `cancel-in-progress: false`, set on the job itself. Workflow-level
  concurrency doesn't count: it serializes runs, not the jobs or matrix legs
  of one run. That means publishers are workflows called with a `head_sha`
  input.
  - **Recorders wait in no group.** A group holds one running and one
    pending job, and a newer pending job cancels the older one
    ([GitHub](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)).
    A recording job replaced while pending would lose its receipt, which
    could be a newer refusal. Ledger appends are compare-and-swap, so
    recording needs no group. A job that uses `mandate.receipt` with
    contents write must not mention `concurrency` at any level, so a job
    can't both record and publish.
  - **Record, then publish:** a recorder queues a reconcile after its append
    (for example a `needs:` job in the group). A pending reconcile that gets
    replaced loses nothing: its replacement was queued later and reads the
    ledger when it runs.
  - **Backstop:** if the ledger or the open PRs move during a reconcile, it
    re-reads and shows the newer decision before returning. It lists every
    run (`filter=all`, paged), so duplicates from a past race are kept
    current.
  - **G4 owner action:** the ruleset that requires `mandate/decision` must
    bind it to the publisher App. Otherwise a commit status or another App's
    check with the same name could satisfy it.

  `serial_violations()` checks this per job over `.github/workflows/`
  (`.yml` and `.yaml`) in the tests and fails closed. Any line under `jobs:`
  it didn't read counts as writing. Within each job and the workflow header
  it scans every line, so blank lines and nesting hide nothing. A job can
  write a scope (`checks`, or `contents` for recording) if, outside
  comments, any of these holds:
  - a line mentions the scope other than as `<scope>: read` or
    `<scope>: none` (so `checks: write`, `permission-checks: write`, flow
    mappings and quoted values all count);
  - for checks, it calls the Checks API directly (`check-runs`,
    `createCheckRun`, `updateCheckRun`), whatever token it uses;
  - a `permissions` key is anything but a block key, `read-all` or `{}` (so
    `write-all`, and quoted or explicit `?` keys);
  - it uses a YAML alias or merge key;
  - it mints an App token with no `permission-*` inputs, because that token
    carries every App permission and the Mandate App has checks and contents
    write.

  A job that uses `mandate.receipt` must also declare `permissions` at the
  job or workflow level rather than rely on the default.

  The check guards against mistakes, not against someone who can edit
  workflows: workflow changes are already owner decisions at the merge gate.

  Jobs that declare no permissions get the repository default, which is
  `read` (`gh api repos/ImranAdan/infra-fleet-public/actions/permissions/workflow`
  → `"default_workflow_permissions":"read"`). Changing that default to
  `write` would bypass this check.
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
