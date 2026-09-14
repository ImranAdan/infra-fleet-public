# Permanent infrastructure

This stack creates resources that survive staging destroy/rebuild cycles:

- the GitHub Actions OIDC provider;
- the `GitHubActions-InfraFleet` automation role and policy; and
- the `load-harness` ECR repository and lifecycle policy.

IAM resources have no hourly charge. ECR storage and transfer can incur AWS
charges.

## Bootstrap

Follow [../../CONFIGURATION.md](../../CONFIGURATION.md). From the repository
root, the supported commands are:

```bash
cp config.example.env config.env
./scripts/bootstrap-permanent.sh
./scripts/bootstrap-permanent.sh --apply
```

The first command that talks to AWS uses the caller's local credentials. Later
workflow runs assume the role created here through GitHub OIDC.

The trust policy is generated from `github_repository`, the deployment branch,
and the GitHub Environment. It does not allow arbitrary repositories, pull
requests, or refs.

## Lifecycle boundary

Do not use `nightly-destroy.yml` or local staging teardown commands against
this directory. Destroying the permanent stack removes CI's AWS identity and
can remove the ECR repository after its normal Terraform deletion checks.

Apply changes through review in the same way as any other infrastructure
change. Recovery after accidental removal requires another local bootstrap
with an AWS administrator identity.

## Outputs

`github_actions_role_arn` is the value for the private repository's
`AWS_GITHUB_ACTIONS_ROLE_ARN` Actions secret. The other outputs identify the
GitHub OIDC provider and ECR repository.

The automation policy still contains broad service permissions. Least-
privilege work must be validated through a complete apply and destroy cycle;
do not describe an unexercised policy as proven.
