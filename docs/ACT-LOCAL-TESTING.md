# Local workflow validation

GitHub Actions is the execution environment, but most of this template's
contracts can be checked locally without cloud credentials or `act`.

## Credentials-free checks

Run the repository contract first:

```bash
./scripts/validate-template-contract.sh
```

It verifies pinned automation dependencies, adopter placeholders, release/image
alignment, shell and JSON syntax, rendered GitOps substitutions, and explicit
workflow token baselines.

Validate Terraform without connecting to HCP Terraform or AWS:

```bash
terraform -chdir=infrastructure/permanent fmt -check
terraform -chdir=infrastructure/permanent init -backend=false -input=false
terraform -chdir=infrastructure/permanent validate

terraform -chdir=infrastructure/staging fmt -check
terraform -chdir=infrastructure/staging init -backend=false -input=false
terraform -chdir=infrastructure/staging validate
```

Exercise the sample application through the supported container path:

```bash
cd applications/load-harness/local-dev
./dev.sh test
./dev.sh up-full
```

The pull-request workflows additionally run actionlint, yamllint, kubeconform,
Kyverno, and Trivy with fixed versions or immutable action references.

## Optional `act` use

[`act`](https://github.com/nektos/act) is useful for listing jobs and finding
basic runner assumptions:

```bash
act -l
```

It is not the acceptance test for this repository. GitHub contexts, reusable
workflow permissions, OIDC, environments, hosted-runner images, and service
behavior can differ. Do not inject AWS, HCP Terraform, GitHub App, or Flux
credentials merely to make an `act` run look complete.

On Apple Silicon, a job that only publishes an `amd64` tool archive may need:

```bash
act -l --container-architecture linux/amd64
```

## Live-only checks

These require an explicitly configured private copy and create or inspect real
external state:

- OIDC role assumption;
- ECR publication;
- Terraform plan/apply/destroy against HCP state;
- EKS and Flux health verification; and
- canary promotion and rollback.

They are not pull-request checks in the public template. Follow
[CONFIGURATION.md](../CONFIGURATION.md), review the billable/destructive action,
and run the matching manual workflow only when that action is intended.
