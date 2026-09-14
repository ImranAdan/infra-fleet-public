# GitHub staging environment

This template supports one deployment environment: `staging`. Create it before
the first deployment under **Settings → Environments → New environment**.
GitHub otherwise creates an unprotected environment the first time a workflow
references it.

## Recommended protection

- Allow deployments only from `main` and release tags matching `v*`.
- Add a required reviewer if another person can approve deployments.
- Do not add a timer unless delayed staging changes are useful to you.

The environment is used by jobs that publish to ECR, apply or rebuild staging,
and clean up or destroy staging. The manual destroy workflow also requires the
operator to type `destroy staging`; the environment review is a second gate,
not a replacement for that target confirmation.

The permanent-stack OIDC policy trusts two exact GitHub subjects:

```text
repo:OWNER/REPOSITORY:ref:refs/heads/main
repo:OWNER/REPOSITORY:environment:staging
```

The branch subject supports jobs that do not use an environment. The
environment subject supports staging deployment jobs after their protection
rules pass. Pull request subjects and arbitrary refs are not trusted.

## Secrets stay at repository scope

The supplied workflows run credentials-free preflight jobs before entering the
environment. Those jobs check whether deployment secrets are complete, so the
secrets listed in [CONFIGURATION.md](../CONFIGURATION.md) must remain repository
Actions secrets for the current implementation.

Moving them to environment scope without also refactoring the preflight jobs
causes an intentional early failure. Never duplicate the same credential as a
Dependabot secret: infrastructure pull requests perform static validation and
do not authenticate to AWS or HCP Terraform.

## What is not included

There is no production environment selector, production Terraform stack, or
promotion workflow. Adding a second environment is a product extension, not a
configuration toggle in this template.

## Troubleshooting

- **Waiting for review:** open the workflow run and select **Review
  deployments**.
- **OIDC access denied:** confirm the environment name is exactly `staging` and
  that `GITHUB_REPOSITORY` used during permanent bootstrap matches this private
  repository.
- **Preflight says secrets are missing:** configure repository Actions secrets;
  environment-only secrets are not visible to preflight.

See [GitHub OIDC setup](GITHUB-OIDC-SETUP.md) for the AWS trust boundary.
