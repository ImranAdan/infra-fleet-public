# Contributing

Contributions are welcome. This repository is a template, so the bar for a
change is slightly different from a normal project: **does it make the
template easier or safer for someone who is not the author to adopt?**

## Before you start

Read [CONFIGURATION.md](CONFIGURATION.md) and
[docs/CREDENTIALS-FREE-TEMPLATE-DDR.md](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md).

The second one matters most: **this repository holds no cloud credentials and
cannot deploy anything.** That is deliberate. Pull requests that add secrets,
add this repository to an IAM trust policy, or make CI depend on cloud access
will be declined.

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

Everything here runs without credentials:

| Check | Scope |
|-------|-------|
| `gitlint` | Commit message format - see [docs/COMMIT-MESSAGES.md](docs/COMMIT-MESSAGES.md) |
| `actionlint` | Workflow syntax |
| `yamllint`, `kubeconform`, Kyverno | Kubernetes manifests and policies |
| `terraform fmt`, `validate` | Terraform |
| `trivy config` | Terraform misconfiguration |
| Unit tests, container build, image scan | The sample application |

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
`perf`, `revert`, `deps`. Title limit is 80 characters.

## Pull requests

`main` is protected. Every change goes through a pull request, `gitlint` must
pass, and review threads must be resolved before merging.

Resolving a thread means replying with what changed, or why you disagree.
Declining a review finding with a reason is a perfectly good outcome - silently
implementing a suggestion you think is wrong is not.

## Security

Do not open a public issue for a security problem. See
[SECURITY.md](SECURITY.md).
