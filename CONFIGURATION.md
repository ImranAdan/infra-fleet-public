# Configuration

Every value this template needs from you, in one place. Nothing in
`infrastructure/`, `k8s/` or `.github/` should need editing — if you find
yourself changing a `.tf` file to insert your own account details, that is a
gap in this document. Please raise it.

> **This repository cannot deploy anything.** It holds no credentials by
> design (see
> [docs/CREDENTIALS-FREE-TEMPLATE-DDR.md](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md)).
> The steps below apply to **your own private copy**.

---

## Before you start

You will need:

| Requirement | Why | Cost |
|-------------|-----|------|
| An AWS account with admin access | The first bootstrap creates the OIDC provider and CI role | Pay-as-you-go |
| An HCP Terraform organisation | State backend. A declared requirement of this project, not optional | Free tier is sufficient |
| A GitHub repository, **private** | Deployment credentials live here | — |
| A registered domain *(optional)* | TLS and public ingress. Skip it and use port-forwarding | — |

Running the full stack costs roughly **$40-50/month** if left up
continuously, dominated by the EKS control plane at about $26 and a NAT
gateway at about $10. Figures are for `eu-west-2` and will differ by region.
See [docs/COST-OPTIMIZATION-GUIDE.md](docs/COST-OPTIMIZATION-GUIDE.md).

---

## Step 1 — copy the template, privately

Click **Use this template** on the repository page, or:

```bash
gh repo create my-infra-fleet --private --template ImranAdan/infra-fleet-public
```

**Make it private before adding any secret.** Everything below assumes a
private repository.

---
## Step 2 — bootstrap the permanent stack, locally

The permanent stack creates the OIDC provider and the IAM role your CI will
later assume. It cannot be created by CI, because CI has no credentials until
it exists.

Run it **once**, from your own machine, with admin credentials:

```bash
cd infrastructure/permanent
export TF_CLOUD_ORGANIZATION="your-hcp-org"
export TF_WORKSPACE="infra-fleet-permanent"
terraform init
terraform apply
terraform output github_actions_role_arn
```

This manual step is deliberate. It is what stops a public template from being
able to reach into anyone's cloud account.

---

## Step 3 — repository secrets

Settings → Secrets and variables → Actions → **Secrets**.

Secrets are masked in workflow logs. Use a secret, not a variable, for
anything you would not want appearing in a log — including values that are
not strictly confidential, such as an account identifier.

| Secret | Required | Where it comes from |
|--------|----------|---------------------|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | yes | `github_actions_role_arn` output from step 2 |
| `TF_API_TOKEN` | yes | HCP Terraform → User settings → Tokens |
| `TF_CLOUD_ORGANIZATION` | yes | Your HCP Terraform organisation name |
| `GRAFANA_ADMIN_PASSWORD` | yes | Choose one |
| `CLOUDFLARE_API_TOKEN` | only with a custom domain | Cloudflare → API token, `Zone:DNS:Edit` |
| `CLOUDFLARE_ZONE_ID` | only with a custom domain | Cloudflare dashboard, zone overview |
| `FLUX_GITHUB_TOKEN` | yes | A GitHub PAT or App token with `repo` scope, for Flux bootstrap |
| `LOAD_HARNESS_API_KEY` | no | Enables the sample application's authenticated endpoints |
| `RELEASE_PLEASE_TOKEN` | no | Legacy alternative to the App below. A PAT reaches every repository your account can see; prefer the App |
| `RELEASE_PLEASE_APP_CLIENT_ID` | no | See [release automation](#release-automation) |
| `RELEASE_PLEASE_APP_PRIVATE_KEY` | no | See [release automation](#release-automation) |

---

## Step 4 — repository variables

Settings → Secrets and variables → Actions → **Variables**.

Variables are **not** masked in logs. Only put values here that you are happy
to see in plain text.

| Variable | Default if unset | Purpose |
|----------|------------------|---------|
| `TF_WORKSPACE_PERMANENT` | `infra-fleet-permanent` | HCP Terraform workspace for the permanent stack |
| `TF_WORKSPACE_STAGING` | `infra-fleet-staging` | HCP Terraform workspace for the ephemeral stack |

Most adopters need neither. They exist so you are not forced to name your
workspaces the way this template does.

---

## Step 5 — Terraform inputs

Values Terraform needs that are specific to your deployment. Set them as
workspace variables in HCP Terraform, or in a local `terraform.tfvars`
(already covered by `.gitignore`).

| Variable | Stack | Required | Purpose |
|----------|-------|----------|---------|
| `domain_name` | staging | only with a custom domain | Root domain, e.g. `example.com`. Defaults to a placeholder |
| `app_subdomain` | staging | no | Subdomain for the sample application. Defaults to `app` |
| `cloudflare_api_token` | staging | only with a custom domain | Also settable as the `CLOUDFLARE_API_TOKEN` secret |
| `cloudflare_zone_id` | staging | only with a custom domain | Cloudflare zone for `domain_name` |

### Not yet parameterised

Two values are still hardcoded in Terraform and **do** need a file edit. Both
are tracked in the sequence in
[docs/CREDENTIALS-FREE-TEMPLATE-DDR.md](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md):

| Value | Where | What to change |
|-------|-------|----------------|
| OIDC trust subject | `infrastructure/permanent/github-oidc.tf` | Replace the repository in `token.actions.githubusercontent.com:sub` with your own, pinned to a ref - see [step 6](#step-6--trust-policy) |
| EKS admin principals | `infrastructure/staging/eks.tf` | `access_entries` names specific IAM principals. Replace them with your own |

They are called out rather than hidden because a template that quietly needs a
`.tf` edit is worse than one that says so.

## Cluster secrets

Two Kubernetes Secrets are referenced by
`k8s/applications/load-harness/deployment.yaml`. Neither is in Git, correctly -
`rebuild-stack.yml` creates both when it provisions the cluster:

| Secret | Key | Source | Required |
|--------|-----|--------|----------|
| `load-harness-secret-key` | `secret-key` | Generated per rebuild with `openssl rand -hex 32` | **yes** |
| `load-harness-api-key` | `api-key` | The `LOAD_HARNESS_API_KEY` repository secret | no - `optional: true`, auth is disabled without it |

Two consequences worth knowing:

**If you apply the manifests without running `rebuild-stack.yml`** - deploying
through Flux alone, for instance - pods stay in `CreateContainerConfigError`,
because `SECRET_KEY` is not optional. Create it by hand if you need to:

```bash
kubectl create secret generic load-harness-secret-key \
  --namespace=applications \
  --from-literal=secret-key="$(openssl rand -hex 32)"
```

**The session key is regenerated on every rebuild**, so anyone logged into the
dashboard is signed out when the stack is rebuilt. That is a reasonable
trade for an ephemeral environment; set a fixed value if it annoys you.

The key must be identical across replicas. The HPA scales this deployment from
1 to 8, and with per-pod keys a login would break as soon as a request landed
on a different pod - which is why it comes from a Secret rather than being
generated in the container.

## Step 6 — trust policy

`infrastructure/permanent/github-oidc.tf` decides which repository may assume
your CI role. It must name **your** repository, and it should not use a
wildcard:

```hcl
"token.actions.githubusercontent.com:sub" = [
  "repo:${var.github_repository}:ref:refs/heads/main",
]
```

`repo:OWNER/REPO:*` matches every ref context including pull requests. On a
public repository that is the difference between "only `main` can deploy" and
"anything that opens a pull request can deploy". Keep it pinned even in a
private repository — it costs nothing.

---

## Release automation

`release-please` opens release pull requests. With the default `GITHUB_TOKEN`
it works, with two caveats: the release pull request needs a manual "Approve
and run" click before its checks execute, and the tag it pushes does **not**
trigger downstream workflows, so no image is published on release.

Setting `RELEASE_PLEASE_APP_CLIENT_ID` and `RELEASE_PLEASE_APP_PRIVATE_KEY`
from a GitHub App removes both limitations. App installation tokens are
short-lived and scoped to a single repository, unlike a personal access token,
which reaches every repository your account can see.

Create an App with **Contents: Read & write** and **Pull requests: Read &
write**, install it on your repository only, and add the client ID and private
key as secrets.

You will also need Settings → Actions → General → Workflow permissions →
**Allow GitHub Actions to create and approve pull requests**, or release pull
requests cannot be opened at all.

---

## Running without a domain

TLS, Cloudflare and public ingress are optional. Without a domain, skip
`CLOUDFLARE_*` and `domain_name` and reach services by port-forwarding:

```bash
kubectl port-forward -n applications svc/load-harness 8080:5000
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

The sample application, metrics, dashboards, canary deployments and DORA
collection all work this way.

---

## Local development needs none of this

The sample application runs with no cloud account, no credentials and no
configuration:

```bash
cd applications/load-harness/local-dev
./dev.sh up-full          # creates .env from .env.example on first run
open http://localhost:8080/ui
```

That path is worth using first, to see what the platform deploys before
deciding whether to deploy it.
