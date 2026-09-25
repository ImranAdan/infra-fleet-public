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
  pull request unread: `READY`, `SURFACE` (a human decides) or `BLOCKED`.

When a verification lesson recurs, encode it as a check (a doctor line, a
contract test, a validator rule) rather than another paragraph here.

## Merging

Every pull request carries a `## Verification` section with the commands run
and what they showed (see `.github/pull_request_template.md`). An agent may
merge a pull request it raised only when
`python3 .claude/skills/merge-gate/merge_ready.py <PR>` reports `READY`, and
must then say what merged and why. `SURFACE` means stop and tell the owner:
a permission, credential, dependency, decision-record or scope change is a
human decision, as is disagreeing with a review finding. `BLOCKED` means fix
and run the gate again.

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
