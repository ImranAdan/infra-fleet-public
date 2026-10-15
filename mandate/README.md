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

Everything under `mandate/` is merge authority in every repository that uses
it, so an agent cannot edit the code that judges its own changes.

Test it through the entry point, the way the merge worker runs it:

```bash
python3 .claude/skills/merge-gate/merge_ready.py --self-test
python3 .claude/skills/merge-gate/judge.py --self-test
```
