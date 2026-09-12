# Staging lifecycle automation

The template has two explicit lifecycle workflows. Neither is scheduled.

| Workflow | Effect |
|---|---|
| `rebuild-stack.yml` | Validates configuration, publishes the sample image, applies staging, bootstraps Flux, and verifies it |
| `nightly-destroy.yml` | Cleans Kubernetes-managed cloud resources, destroys only the staging Terraform workspace, and verifies removal |

Despite its historical filename, `nightly-destroy.yml` is manual. This avoids
surprising a template adopter with a scheduled destructive action.

## Resource boundary

`infrastructure/permanent/` contains GitHub OIDC, the automation role, and ECR.
It survives staging teardown. `infrastructure/staging/` contains billable EKS,
network, and workload-supporting resources and is the only stack the destroy
workflow targets.

Both workflows must be dispatched from `main`. Jobs that mutate AWS use the
protected `staging` GitHub Environment. HCP Terraform state locking remains
enabled during destroy.

## Rebuild

Configure the private repository as described in
[../CONFIGURATION.md](../CONFIGURATION.md), then dispatch **Rebuild Stack**.
Its preflight fails before any AWS call when configuration is missing or
partial. The first rebuild is allowed when no earlier infrastructure-apply run
exists.

The optional `force_rebuild` input bypasses only the main-branch workflow
health gate; it does not bypass configuration, AWS authentication, Terraform,
or cluster verification.

## Destroy

Dispatch **Destroy Staging Stack (Manual)** from `main` and type
`destroy staging` exactly. Cleanup first asks the Kubernetes controllers to
remove Ingresses, load balancers, and volumes, then checks cluster-tagged AWS
resources before Terraform destroy. The cleanup and Terraform jobs both use
the protected `staging` environment.

The `force` option may proceed when cleanup verification fails. It does not
expand the Terraform target beyond the staging workspace, but it can leave
orphaned billable resources; use it only after reading the cleanup logs.

For a local operator path, `ops/local-destroy.sh` loads the HCP workspace from
the ignored `config.env` and requires an explicit flag:

```bash
./ops/local-destroy.sh --confirm-staging-destroy
```

No command in this document destroys the permanent stack.
