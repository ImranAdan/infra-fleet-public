# Agent guidelines

Read by any coding agent working in this repository (Codex, Claude Code and
others). `CLAUDE.md` imports this file.

## What this repository is

A platform that runs one application, selected by the app contract in
`k8s/fleet-app/`, on a local kind cluster or AWS staging. The platform names no
application; `docs/APPLICATION-CONTRACT.md` explains the split. Infra Fleet
Advisor reviews this repository against declared intent, and its intent gate
runs on every pull request.

## Verification

"It renders", "it compiles" and "CI is green" are not evidence that behavior
works. Before reporting a change as done, verify it against the real artifact
and show the evidence: the exact commands, their output and exit codes.

**Match the check to the change:**

| Change | Check |
|---|---|
| Manifests, overlays, policies | `./scripts/validate-template-contract.sh`, which renders both profiles and runs the contract tests; for behavior, a live drive with `verify-fleet` |
| The app contract or an app | `tests/profiles/app-contract.sh`, then a live swap with `verify-fleet` |
| Scripts or `./fleet` | Their `tests/profiles/*.sh`, then the real command on the local profile |
| Canary, gates, gateway | `./fleet test --profile local`, which promotes and rolls back for real |
| Metrics or dashboards | `verify-fleet`'s ground-truth drive: numbers must equal what you sent |
| Anything the advisor reads | Its intent gate locally: `../infra-fleet-advisor-public/scripts/intent-gate.sh` |

**Evidence standard.** Push every claim as far down this ladder as is cheap,
and say where it stopped: stated, pointed at a real `file:line`, walked
through, **ran** (a script or test that fails loudly if you are wrong), or
**reproduced on the running cluster**. Compare against a ground truth you
control: a count you sent, a revision you committed, a fault you injected. A
populated dashboard is not proof its numbers are right. Say `inconclusive`
when a check could not run; never report a path as verified through another.

**Tests.** A test calls the code the way its users do and asserts an observed
result against a literal expected value. If it would still pass with the code
under test stubbed out, rewrite or delete it. For a bug with a cheap test
path, write the failing test first and show it failing before the fix.

**Sequence.** Break multi-step work into small units that each end in a
checkable state, and check each before starting the next. Order commits so
the history proves the work: the failing check, then the fix.

**Skills.** Project skills live in `.claude/skills/`:

- `verify-fleet`: launch, health-check (`doctor.sh`), drive and collect
  evidence from the local cluster, with a feature map of what proves each
  behavior. Use it before claiming a fleet change works.
- `blast-radius`: what a change breaks beyond its diff, with the places grep
  cannot see in this repository.
- `merge-gate`: `merge_ready.py <PR>` decides whether an agent may merge a
  pull request unread: `READY`, `PARK` (the owner decides), `JUDGE` (the
  independent judge decides) or `BLOCKED`.

When a verification lesson recurs, encode it as a check (a doctor line, a
contract test, a validator rule) rather than another paragraph here.

## Merging

Every pull request carries a `## Verification` section with the commands run
and what they showed (see `.github/pull_request_template.md`). An agent may
merge a pull request it raised only when
`python3 .claude/skills/merge-gate/merge_ready.py <PR>` reports `READY`, and
must then say what merged and why. An agent never adds the `owner-approved`
label and never posts or imitates a merge-judge comment. The workflow binds an
owner-applied label to the exact head SHA; a label without that trusted record
does not approve a merge. `PARK` means stop and tell the owner. `JUDGE` means
wait for the independent base-branch judge. `BLOCKED` means fix the reported
defect and run the gate again.

## When a decision is not yours

Decisions should almost never reach the owner: constant approvals defeat the
point. The advisor is the captain. Work down this ladder and stop at the first
rung that decides:

1. **Evidence.** If tests, drills or a verify skill prove one option and not
   the other, take the proven one.
2. **Declared intent.** The advisor's intent catalog
   (`infra-fleet-advisor-public/intent/`) records the owner's standing
   decisions, and the intent gate enforces them on every fleet pull request.
   If a position covers the choice, follow it.
3. **Precedent.** If the same question was answered before
   (`gh issue list --label decided --state all`), follow that answer.
4. **Reversibility.** If the choice is cheap to undo and within declared
   intent, decide yourself, state the reasoning and the alternative you
   rejected in the pull request, and move on.

Only a **deadlock** goes to the owner: declared intent is silent or two
positions conflict, *and* the choice is expensive to reverse; or only the
owner can act (a secret, billing, or an account or organisation setting). Then
open an issue from the **Decision needed** template
(`.github/ISSUE_TEMPLATE/decision.md`): a short TL;DR, evidence for each
option, one decision card per question with your recommendation, and a reply
template. The owner answers with a comment and the decision collector records
it; carry on with other work meanwhile. When a deadlock reveals a standing
preference, propose it as declared intent, so the same question never
reaches the owner twice.

## Picking up decisions

The **Decision collector** workflow records the owner's answers on decision
issues as they arrive and labels an issue `decided` once every card is
answered, so the owner never has to report back. At the start of work, run
`gh issue list --label decided --state open`. The collector's summary comment
holds the record, `<!-- decisions {"D1": "A", ...} -->`. Act on it, then close
the issue with a comment linking the pull request that carries it out. Never
post `D1:`-style answers yourself: only the owner's count.

## Shared cluster

The local cluster is shared by everyone working in this checkout. Run
`.claude/skills/verify-fleet/doctor.sh` before driving it, and do not deploy
to it, test on it or tear it down while another agent is using it.

## Conventions

- Conventional Commit subjects of at most 72 characters.
- Deploy only committed revisions; change the cluster through Git and
  `./fleet sync`, never by patching live objects.
- Keep documentation beside the behavior it describes; update both in one
  change.
