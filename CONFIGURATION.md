# Configure a private fleet

This is the shortest supported path from the public template to a working
staging fleet. The public repository is deliberately credentials-free and
never deploys to AWS. These steps apply to a private repository created from
the template.

The supported deployment is one `eu-west-2` staging cluster. A production
environment is not included.

> **Before deploying publicly:** the canary implementation currently uses the
> retired community `ingress-nginx` controller. It receives no further security
> fixes. Treat cloud deployment as a private learning environment until the
> Gateway API migration is complete and live-cycle tested.

## Prerequisites

You need:

- an AWS account and local administrator credentials for the one-time bootstrap;
- Terraform 1.14, the AWS CLI, and Git;
- an HCP Terraform organisation on a plan that supports two workspaces;
- a private GitHub repository created from this template; and
- optionally, a hostname managed in Cloudflare for public TLS ingress.

The stack is not free. Read the illustrative estimate in
[README.md](README.md#cost-optimization) before applying it.

## 1. Create a private repository

Use **Use this template** on GitHub, or run:

```bash
gh repo create my-infra-fleet --private --template ImranAdan/infra-fleet-public
git clone git@github.com:YOUR_OWNER/my-infra-fleet.git
cd my-infra-fleet
```

Keep the deployment repository private before adding credentials.

## 2. Create the HCP Terraform workspaces

Create these two CLI-driven workspaces in your HCP Terraform organisation:

- `infra-fleet-permanent`
- `infra-fleet-staging`

Set **Execution Mode** to **Local** for both. HCP Terraform stores and locks
state; Terraform commands and AWS calls run on your machine during bootstrap
and on GitHub-hosted runners afterward. Remote execution is not supported by
the supplied authentication path.

Authenticate the local Terraform CLI:

```bash
terraform login
```

## 3. Fill in the identifier file

```bash
cp config.example.env config.env
```

Edit `config.env`. It is ignored by Git and contains identifiers, not
credentials:

```dotenv
GITHUB_REPOSITORY=YOUR_OWNER/my-infra-fleet
GITHUB_DEPLOYMENT_BRANCH=main
GITHUB_DEPLOYMENT_ENVIRONMENT=staging
TF_CLOUD_ORGANIZATION=YOUR_HCP_ORGANISATION
TF_WORKSPACE_PERMANENT=infra-fleet-permanent
TF_WORKSPACE_STAGING=infra-fleet-staging
EKS_ADMIN_PRINCIPAL_ARNS_JSON='[]'
```

`EKS_ADMIN_PRINCIPAL_ARNS_JSON` is optional. Leave it as `[]` unless a local
IAM role or user also needs `cluster-admin`. Prefer an IAM Identity Center role
to a long-lived IAM user.

## 4. Bootstrap permanent AWS resources

The permanent stack creates ECR and the narrowly trusted GitHub Actions OIDC
role. CI cannot create its own initial identity, so this one apply runs on your
machine with your current AWS credentials.

Review a plan first, then opt in to the apply:

```bash
./scripts/bootstrap-permanent.sh
./scripts/bootstrap-permanent.sh --apply
```

The script prints `github_actions_role_arn` after a successful apply. It does
not configure GitHub or persist AWS credentials.

If the AWS account already has GitHub's account-wide OIDC provider, the script
stops before planning and prints the exact import command. Run that import,
review the next plan carefully, and then rerun the script.

## 5. Configure GitHub Actions

Under **Settings → Secrets and variables → Actions**, add these secrets:

| Secret | Required | Source |
|---|---:|---|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | yes | `github_actions_role_arn` from bootstrap |
| `TF_API_TOKEN` | yes | HCP Terraform user or team token |
| `TF_CLOUD_ORGANIZATION` | yes | your HCP Terraform organisation name |
| `FLUX_GITHUB_TOKEN` | yes | fine-grained token scoped to this repository with Contents read/write |
| `GRAFANA_ADMIN_PASSWORD` | yes | a unique password; it is written to a Kubernetes Secret |
| `LOAD_HARNESS_API_KEY` | no | enables API-key protection for the sample app |
| `CLOUDFLARE_API_TOKEN` | with automated DNS | Cloudflare token with Zone DNS edit |
| `CLOUDFLARE_ZONE_ID` | with automated DNS | Cloudflare zone overview |
| `RELEASE_PLEASE_APP_CLIENT_ID` | no | optional release GitHub App client ID |
| `RELEASE_PLEASE_APP_PRIVATE_KEY` | no | matching private key |

`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` must be present together.
Do not use repository variables for secrets.

Add these repository variables:

| Variable | Default | Purpose |
|---|---|---|
| `TF_WORKSPACE_PERMANENT` | `infra-fleet-permanent` | permanent HCP workspace |
| `TF_WORKSPACE_STAGING` | `infra-fleet-staging` | staging HCP workspace |
| `EKS_ADMIN_PRINCIPAL_ARNS_JSON` | `[]` | JSON array passed to Terraform |
| `APP_HOSTNAME` | `app.example.invalid` | optional real hostname for TLS ingress |
| `ACME_EMAIL` | `nobody@example.invalid` | Let's Encrypt contact; set with `APP_HOSTNAME` |

Set `APP_HOSTNAME` and `ACME_EMAIL` together. If they are omitted, the sample
application and Grafana remain available by port-forwarding, while public TLS
ingress intentionally uses the non-routable `.invalid` hostname. If the two
Cloudflare secrets are also present, the rebuild workflow creates or updates
the hostname's CNAME automatically. You may manage the same DNS record outside
Cloudflare instead.

Create a GitHub Environment named `staging` and restrict deployments to `main`
and release tags matching `v*`. The OIDC role trusts that exact environment and
the configured deployment branch; it does not trust pull request subjects or
arbitrary refs.

## 6. Build the fleet

Run **Actions → Rebuild Stack → Run workflow** from `main`.

The workflow:

1. checks every required setting before making an AWS call;
2. tests, builds, scans, and publishes the current sample image to your ECR;
3. applies the staging Terraform workspace;
4. creates runtime-only application and Grafana secrets;
5. bootstraps Flux against your repository; and
6. verifies the cluster and Flux reconciliation.

Expect the first run to take roughly 25–40 minutes. It is intentionally manual
because it creates billable resources.

## 7. Connect

Without a domain:

```bash
aws eks update-kubeconfig --name staging --region eu-west-2
kubectl port-forward -n applications svc/load-harness 8080:5000
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

Open `http://localhost:8080/ui` and `http://localhost:3000`. The Grafana user is
`admin`; its password is the `GRAFANA_ADMIN_PASSWORD` secret you supplied.

With a configured domain, use `https://APP_HOSTNAME/ui` after DNS and
certificate issuance complete.

## Day-two behavior

- Infrastructure pull requests run formatting, validation, and Trivy without
  cloud credentials. They never assume the deployment role.
- Infrastructure changes merged to `main` apply only when all three deployment
  secrets are configured. With none, deployment skips successfully; a partial
  configuration fails clearly.
- Release tags, and rebuilds, test and scan the sample image before publishing
  it to ECR. The public template performs the same checks but skips publishing.
- `nightly-destroy.yml` is manual. Run it when you want to remove the staging
  stack; type `destroy staging` when prompted. The permanent OIDC role and ECR
  repository remain.

## Runtime secrets

No Kubernetes Secret is committed. `rebuild-stack.yml` creates:

| Secret | Purpose |
|---|---|
| `applications/load-harness-secret-key` | shared Flask session key, regenerated each rebuild |
| `applications/load-harness-api-key` | optional sample API authentication |
| `observability/grafana-admin-credentials` | Grafana administrator credentials |

Applying `k8s/` without the rebuild workflow is not a supported bootstrap path,
because those runtime secrets and the Flux substitution ConfigMap would be
missing.

Each rebuild also changes a non-secret runtime configuration revision in that
ConfigMap. Flux then rolls the application pods so rotated Flask/API keys take
effect; an existing Grafana deployment is restarted after its administrator
Secret is updated.

Removing `LOAD_HARNESS_API_KEY` and running a rebuild removes the
workflow-owned Kubernetes Secret so authentication is actually disabled; an
old key is not left active.

## Release automation

Release Please can open a release PR with the default `GITHUB_TOKEN`, but events
created by that token do not trigger the normal pull-request or tag workflows.
Run those checks manually, or, for an automated chain, create a
repository-scoped GitHub App with **Contents: read/write** and **Pull requests:
read/write**, then set
`RELEASE_PLEASE_APP_CLIENT_ID` and `RELEASE_PLEASE_APP_PRIVATE_KEY`.

Also enable **Settings → Actions → General → Allow GitHub Actions to create and
approve pull requests** if you want the release workflow to open PRs.

## Local application development

The sample application needs none of the cloud configuration:

```bash
cd applications/load-harness/local-dev
./dev.sh up-full
open http://localhost:8080/ui
```
