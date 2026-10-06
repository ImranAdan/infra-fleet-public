# GitHub deployment environments

[Documentation index](README.md)

The template maps deployment profiles to two GitHub Environments. A job that
references an environment creates a deployment record for its exact workflow
revision and is subject to that environment's protection rules.

| Fleet profile | GitHub Environment | Lifetime | Purpose |
|---|---|---|---|
| `local` | `local` | Ephemeral | Prove Flux, Kyverno, networking, monitoring, canary promotion and rollback on kind, then tear it down |
| `aws-staging` | `staging` | Persistent until destroyed | Publish images, apply or rebuild EKS, and clean up or destroy staging |

The AWS onboarding coordinator creates `staging` before its first deployment
and restricts it to `main` and release tags matching `v*`. Repository
administrators own required reviewers and wait timers. The first job to reference `local`, whether from a pull request, the schedule
or a dispatch, creates it with no protection rules; configure `local` before
then if required reviewers must apply to that first run.

## Local acceptance

**Local Kubernetes** runs on pull requests to `main` that change runtime paths
(`k8s/`, `scripts/`, `platform/`, `applications/`, `tests/profiles/`, `fleet`),
every Monday at 05:37 UTC against `main`, and on dispatch:

```bash
gh workflow run local-kubernetes.yml --ref YOUR_BRANCH
```

The workflow checks out the exact commit and records it in the `local`
Environment. Pull requests create one profile with the selected app; weekly
and manual runs create one profile per app contract. Every job runs the complete
acceptance suite and always requests teardown. The environment URL points to
the workflow evidence because the cluster does not outlive the hosted runner.
The merge gate waits for these checks like any other. A newer push to a pull
request cancels that pull request's earlier run. Adding a required reviewer to
`local` gates every run, including pull requests and the weekly schedule.

## AWS staging protection

`./fleet setup --profile aws-staging --apply` creates `staging` when absent and
adds the supported branch and tag policies. It never replaces an existing
environment's reviewers or wait timer. If the existing environment uses an
incompatible branch-policy mode, setup stops for manual review. Recommended
additional protection:

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
rules pass. Pull request subjects and arbitrary refs are not trusted. The GitHub
Environment is therefore named `staging` even though the facade profile is
named `aws-staging`. Renaming it without migrating the AWS trust policy breaks
OIDC authentication.

## Secrets stay at repository scope

The supplied AWS workflows run configuration preflight jobs before entering the
environment. Those jobs check whether deployment secrets are complete, so the
secrets listed in [CONFIGURATION.md](../CONFIGURATION.md) must remain repository
Actions secrets for the current implementation.

Moving them to environment scope without also refactoring the preflight jobs
causes an intentional early failure. Never duplicate the same credential as a
Dependabot secret: infrastructure pull requests perform static validation and
do not authenticate to AWS or HCP Terraform. The local Environment requires no
AWS, Terraform or GitHub write credentials.

## Product boundary

There is no production environment selector, production Terraform stack or
promotion workflow. Adding production is a product extension. The local
Environment proves only the local profile and shared contracts; it does not
certify AWS routing, IAM, DNS, TLS, ECR or EKS behavior.

## Troubleshooting

- **Waiting for review:** open the workflow run and select **Review
  deployments**. This occurs only when the selected environment has reviewers.
- **Local deployment is unavailable afterward:** expected; use the linked
  workflow run for evidence or run `./fleet up --profile local` on a workstation
  for an interactive cluster.
- **OIDC access denied:** confirm the AWS environment name is exactly `staging`
  and that `GITHUB_REPOSITORY` used during permanent bootstrap matches this
  private repository.
- **Preflight says secrets are missing:** configure repository Actions secrets;
  environment-only secrets are not visible to preflight.

See [GitHub's environment documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
and [GitHub OIDC setup](GITHUB-OIDC-SETUP.md).
