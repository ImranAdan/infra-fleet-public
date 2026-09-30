# Contributing

Contributions are welcome. This repository is a template, so the bar for a
change is slightly different from a normal project: **does it make the
template easier or safer for someone who is not the author to adopt?**

## Before you start

Read [CONFIGURATION.md](CONFIGURATION.md) and
[Template Deployment Boundaries](docs/PUBLIC-TEMPLATE-BOUNDARY-DDR.md).

Changes must preserve the documented template adoption and deployment
boundaries. Explain any proposed change to workflow access or IAM trust in its
design context.

## What is especially welcome

- **Anything that removes a manual step from adoption.** If you had to edit a
  `.tf` file to insert your own account details, that is a gap in
  `CONFIGURATION.md` and worth reporting even without a fix.
- **Documentation that turned out to be wrong.** Instructions referencing paths
  that no longer exist, or describing automation that is not configured, are
  bugs. They were the largest category of defect in the last two reviews.
- **Reducing the required configuration.** Every value that can have a working
  default should have one.

## What CI checks

Pull requests receive these static and application checks:

| Check | Scope |
|-------|-------|
| `gitlint` | Commit message format, configured in [`.gitlint`](.gitlint) |
| `actionlint` | Workflow syntax |
| `yamllint`, `kubeconform`, Kyverno | Kubernetes manifests and policies |
| `terraform fmt`, `validate` | Terraform |
| `trivy config` | Terraform misconfiguration |
| Unit tests, container build, image scan | The sample application |
| Declared intent | Advisor positions affected by the proposed Fleet change |
| Local Kubernetes | Full kind acceptance for pull requests that change runtime paths |

`terraform plan` and `apply` do **not** run here, so Terraform changes are
validated for syntax and static correctness only. Say so in the pull request
if a change needs a real plan to be confident in it.

## Commit messages

Conventional Commits, enforced by CI:

```
fix(iam): scope the github actions role away from service wildcards
docs: correct the destroy schedule claims
ci(flux): pin the flux cli by commit and version
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`,
`perf`, `revert`, `deps`. Title limit is 80 characters. `pip install -r
requirements-dev.txt && ./scripts/install-git-hooks.sh` runs the same check
locally. Release Please versions Load Harness from `feat` and `fix` commits.

## Pull requests

`main` is protected. Every change goes through a pull request, `gitlint` must
pass, and review threads must be resolved before merging.

Resolving a thread means replying with what changed, or why you disagree.
Declining a review finding with a reason is a perfectly good outcome - silently
implementing a suggestion you think is wrong is not.

## Automated merge decisions

Repository agents use the local merge gate after CI and review are complete.
The policy lets deterministic exact-head evidence decide reversible categories.
It also requires a successful configured intent check whose Actions run comes
from that check's declared workflow; the standard and retargeted gates are
alternatives, while a missing or same-name substitute fails closed. Changes to
durable authority, access, migrations, declared intent and the merge system
remain with the repository owner.

The pull request template opts same-repository branches into the autonomous
worker. Keep the marker to merge when the gate reaches `READY`; remove it to
hold the PR. The worker reruns whenever a pull-request check workflow
completes, and hourly.

This default path needs no model or API key. The Anthropic transport remains
available only if a future policy category explicitly uses the `judge` decider.
The required intent gate retains its veto over every approval path. See the
[merge-gate guide](.claude/skills/merge-gate/SKILL.md) for verdicts and the
exact-head merge command.

## Security

Do not open a public issue for a security problem. See
[SECURITY.md](SECURITY.md).
