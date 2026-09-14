# GitHub Actions OIDC authentication

The private repository created from this template authenticates to AWS with a
short-lived GitHub Actions OIDC token. No AWS access key is stored in GitHub.

The one-time bootstrap is documented in
[../CONFIGURATION.md](../CONFIGURATION.md). It must run locally because CI
cannot create the role it needs in order to authenticate.

## What the permanent stack creates

`infrastructure/permanent/` creates:

- the AWS IAM OIDC provider for `token.actions.githubusercontent.com`;
- the `GitHubActions-InfraFleet` role;
- its infrastructure-automation policy; and
- the permanent `load-harness` ECR repository.

The role trust policy is generated from these Terraform variables:

```text
github_repository              = OWNER/REPOSITORY
github_deployment_branch       = main
github_deployment_environment  = staging
```

It accepts exactly two GitHub OIDC subjects:

```text
repo:OWNER/REPOSITORY:ref:refs/heads/main
repo:OWNER/REPOSITORY:environment:staging
```

Pull-request subjects and arbitrary repositories or refs are not trusted.

## GitHub Environment boundary

GitHub omits the source branch from an OIDC subject when a job uses an
Environment. Restrict the `staging` Environment to the `main` branch and
release tags matching `v*`; the IAM subject alone cannot enforce both the
Environment and branch.

The repository secret `AWS_GITHUB_ACTIONS_ROLE_ARN` must contain the
`github_actions_role_arn` Terraform output. Workflows request `id-token: write`
only in jobs that need AWS.

## Permission limitation

The trust boundary is narrow, but the attached AWS permissions remain broad
enough to create and destroy this learning stack. In particular, IAM
administration is not yet resource-scoped. Do not describe the role as least
privilege or reuse it for a production account until a complete
apply/rollout/destroy cycle has validated a tighter policy.

## Verification

After the local bootstrap:

```bash
terraform -chdir=infrastructure/permanent output github_actions_role_arn
aws iam get-role --role-name GitHubActions-InfraFleet \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
```

If the AWS account already has GitHub's OIDC provider, import it into the HCP
Terraform permanent workspace instead of creating a duplicate.
