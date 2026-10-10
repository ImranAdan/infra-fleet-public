# Agent guidelines

Read by any coding agent working in this repository (Codex, Claude Code and
others). `CLAUDE.md` imports this file.

## What this repository is

A platform that runs the application selected by the contract in
`k8s/fleet-app/` on a local kind cluster or AWS staging. The local profile also
offers an isolated control plane that can launch other contracted applications
on demand. The platform names no application; `docs/APPLICATION-CONTRACT.md`
and `docs/APPLICATION-CONTROL-PLANE.md` explain the split. Infra Fleet Advisor
reviews this repository against declared intent, and its intent gate runs on
every pull request.

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
  optional independent judge decides) or `BLOCKED`.

When a verification lesson recurs, encode it as a check (a doctor line, a
contract test, a validator rule) rather than another paragraph here.

## Merging

Every pull request carries a `## Verification` section with the commands run
and what they showed (see `.github/pull_request_template.md`). An agent may
merge a pull request it raised only by rerunning
`python3 .claude/skills/merge-gate/merge_ready.py <PR> --merge` after the gate
reports `READY`, or by leaving the template's `<!-- autonomous-merge -->`
marker for the trusted default-branch worker to run that exact command. Both
paths bind the merge to the checked head SHA. Remove the marker to hold a PR
open. Dependabot PRs that only move versions need neither the marker nor a
Verification section: the worker considers them and the gate accepts their
exact-head checks as evidence (see `.claude/skills/merge-gate/SKILL.md`). An agent must say what merged and why. It never adds the `owner-approved`
label and never posts or imitates a merge-judge comment. An owner approval is
the repository owner adding `owner-approved` after every check run on the
current head started: GitHub records both with server time, so a push after the
approval starts new checks and unbinds it. No `pull_request_target` workflow is
involved; GitHub blocks that trigger on public repositories by default from
2026-11-02. `PARK` means stop and tell the owner. `JUDGE` means wait
for the independent base-branch judge. `BLOCKED` means fix the reported defect
and run the gate again.

The default path is key-free. Reversible categories marked `evidence` in the
decision policy can reach `READY` only after every head check passes and the
successful declared-intent check—standard or retargeted—is traced to its
configured GitHub Actions workflow on that exact head. Added authority,
credentials, IAM, permanent infrastructure, migrations, declared intent and
the merge system remain owner decisions. The optional Anthropic path is
dormant unless a future policy category explicitly names `judge` as its
decider. No model decision can override declared intent; the advisor is the
first authority.

The autonomous worker runs after the universal intent gate, after the slowest
applicable check classes, and when an external status or review completes. A
six-hour schedule is a recovery backstop. It considers only non-draft PRs whose head branch belongs to
this repository and whose body contains the opt-in marker. `READY` merges;
`PARK`, `JUDGE`, failed evidence and unresolved review stay open. Advisor
mechanical remediation uses a read-only planning job and opens an opted-in Fleet
PR. Because token-authored PRs suppress ordinary pull-request events, trusted
Fleet code explicitly dispatches read-only validation on the exact generated
branch; it receives no path around this gate.

## Autonomy

The owner runs this project with autonomous agents and does not want work to
wait for approval. Decide, record the decision and the alternative you
rejected in the pull request, and keep going. Docs, decision records and
earlier statements describe the current design, not a fixed law: when a
better design needs one changed, change it in the same pull request and say
why.

Without asking first you may push branches you created and delete them once
merged; open, update, comment on, label and close issues and pull requests;
merge through the merge gate; trigger, re-run or cancel workflows, including
to verify your own work; and change a repository's security-and-analysis
settings (Dependabot alerts and security updates, secret scanning) when the
change moves it toward declared intent. State each outward action, and how to
undo it, in the pull request or issue it serves.

**Owner-only actions.** Never do these without the owner: add
`owner-approved` or post or imitate a merge-judge comment; create, read or
rotate a secret or credential; add or widen a permission held by a token,
GitHub App or workflow; change branch protection, rulesets, the Actions policy
or merge settings; delete a repository, release, tag or data; force-push over
work you did not author; spend on a paid API beyond the usage CI already
incurs. When one is the next step, open a **Decision needed** issue (below)
and carry on with other work.

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
