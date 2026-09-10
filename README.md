<div align="center">

# Infrastructure Fleet

**A complete, production-shaped Kubernetes platform you can fork — and a sample app that puts it through its paces.**

EKS · GitOps · canary deployments with automatic rollback · Prometheus and Grafana · DORA metrics · one-command teardown to keep the bill honest

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.32-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Flux](https://img.shields.io/badge/GitOps-Flux%20v2.7.3-5468FF?logo=flux&logoColor=white)](https://fluxcd.io/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform&logoColor=white)](https://developer.hashicorp.com/terraform)
[![No credentials](https://img.shields.io/badge/secrets%20in%20this%20repo-none-2ea44f)](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md)

[Try it locally](#try-it-locally-first) · [What you get](#what-you-get) · [Make it yours](CONFIGURATION.md) · [Docs](docs/README.md)

</div>

---

## Try it locally, first

No AWS account. No credentials. No configuration.

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
cd infra-fleet-public/applications/load-harness/local-dev
./dev.sh up-full
```

First run builds the image, so give it a few minutes; after that it is seconds.

Open **http://localhost:8080/ui** and press a button — the dashboard drives
real CPU and memory load, and you watch Prometheus and Grafana react to it live.

That is the same application the cluster runs, the same metrics the canary
analysis judges, and the same dashboards. If you like what you see, the rest of
this repository is how it gets to production.

---

## What you get

Fork this and you have a platform that does the following, on day one:

| | |
|---|---|
| **Ships safely** | A push to `main` builds, scans and publishes an image, Flux picks it up, and Flagger rolls it out as a canary — promoting on success rate and p99 latency, rolling back automatically when they slip |
| **Tells you the truth** | Prometheus, Grafana and a DORA metrics pipeline: deployment frequency, lead time, change failure rate, time to restore |
|  **Costs about $43/month** | Spot instances, a slim Flux install, nginx over ALB, and a one-command teardown for when you are not using it |
| **Proves itself in CI** | Terraform validated and scanned, manifests schema-checked, Kyverno policies enforced, images scanned with Trivy, commit messages linted, releases cut by release-please |
| **Is safe to fork** | This repository holds no credentials and appears in no IAM trust policy. There is nothing here to leak |

---

## Why this one

Most "reference platform" repositories are a diagram and a `terraform apply`
that stopped working eleven months ago. Three things make this different.

**It is exercised, not just published.** Every claim in this README is checked
in CI or was verified by running it. The sample application is not a
placeholder — it generates real load so autoscaling, canary analysis and the
dashboards have something true to measure.

**It admits what it costs.** Kubernetes reference architectures are usually
priced at zero because nobody ran them. This one is about $26 for the EKS
control plane, $10 for a NAT gateway and $7 of spot capacity in `eu-west-2`, and
it ships with a destroy workflow, because the honest answer to "how do I make
it cheaper" is "turn it off when you are not using it".

**It cannot hurt you.** The repository you are reading has no secrets and no
cloud access by design — deliberately, and
[written down](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md). Deployment happens in
your own private copy, with your own credentials, after a bootstrap step you run
yourself. Forking it grants nobody anything.

---

## Make it yours

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git my-infra-fleet
cd my-infra-fleet
rm -rf .git && git init && git add -A && git commit -m "chore: initial commit from infra-fleet template"
gh repo create my-infra-fleet --private --source=. --push
```

**Make it private before adding any secret.**

Then follow **[CONFIGURATION.md](CONFIGURATION.md)** — every value you need to
supply, where each one comes from, and what you can skip. You need an AWS
account and an HCP Terraform organisation; a cluster build takes roughly 25
minutes. A custom domain is optional; without one, port-forwarding reaches
everything.

The sample application is meant to be replaced. When you are ready, swap in your
own — keep a `/health` and a `/metrics` endpoint and the probes, autoscaling and
canary analysis carry on working. See
[replacing the Harness](applications/load-harness/docs/APPLICATION-ROADMAP.md#extending-or-replacing-the-harness).

---
## Architecture

![Platform Architecture](docs/ARCHITECTURE.png)

**Key Flows:**
- **CI/CD**: Push → GitHub Actions → Build/Test → ECR → Flux Image Automation → Deploy
- **Progressive Delivery**: New version → Flagger canary → Traffic shifting → Metrics analysis → Promote/Rollback
- **Observability**: Applications → Prometheus scrape → Grafana dashboards → DORA metrics

See [docs/README.md](docs/README.md) for detailed architecture diagram.

---

## Key Features

### Progressive Delivery with Flagger

Automated canary deployments with metric-based promotion:

```yaml
# Canary configuration
analysis:
  interval: 30s
  threshold: 5
  maxWeight: 50        # Max 50% traffic to canary
  stepWeight: 10       # 10% increments
  metrics:
    - name: nginx-request-success-rate
      thresholdRange:
        min: 99        # Requires 99% success rate
    - name: nginx-request-duration
      thresholdRange:
        max: 500       # p99 latency < 500ms
```

**What happens on deploy:**
1. New version creates canary pods
2. Traffic gradually shifts: 10% → 20% → 30% → 40% → 50%
3. Prometheus metrics analyzed at each step
4. Success → Promote to primary | Failure → Automatic rollback

### Dashboard UI

Web-based interface for load testing and monitoring:

- **Load Tests**: CPU, Memory, Distributed Cluster tests
- **Live Metrics**: Real-time Prometheus integration
- **Per-Pod Monitoring**: CPU/Memory per pod with HPA visibility
- **Dark Mode**: Full dark theme support

Access at `https://<your-subdomain>.<your-domain>/ui`, or by port-forwarding
if you are running without a domain.

### DORA Metrics

Track engineering performance with automated metrics collection:

| Metric | Implementation |
|--------|----------------|
| Deployment Frequency | Workflow + Flux deploy events |
| Lead Time for Changes | Commit → Deploy timestamp diff |
| Change Failure Rate | Workflow failures + Flagger rollbacks |
| MTTR | Failure → Recovery time tracking |

### TLS/HTTPS

Automated certificate management:
- **cert-manager** with Let's Encrypt ClusterIssuer
- **Cloudflare DNS** automatically updated on cluster rebuild
- **nginx-ingress** handles TLS termination

---

## Repository Structure

```
<your-repo>/
├── infrastructure/                 # Terraform IaC
│   ├── permanent/                  # OIDC, ECR (never destroyed)
│   └── staging/                    # EKS cluster (ephemeral)
│
├── applications/
│   └── load-harness/               # Python Flask application
│       ├── src/load_harness/       # Application code
│       │   ├── services/           # JobManager, Prometheus, Metrics providers
│       │   ├── workers/            # CPU/Memory background workers
│       │   ├── middleware/         # Auth, Chaos, Security headers
│       │   ├── dashboard/          # Web UI (routes.py)
│       │   └── templates/          # HTMX + Tailwind templates
│       ├── tests/                  # Test suite (104 tests)
│       ├── monitoring/             # Grafana dashboards (JSON)
│       └── local-dev/              # Docker Compose dev environment
│
├── k8s/                            # GitOps manifests
│   ├── flux-system/                # Flux controllers + kustomizations
│   ├── infrastructure/             # Helm releases, namespaces
│   │   ├── cert-manager/           # TLS certificates
│   │   ├── flagger/                # Progressive delivery
│   │   ├── nginx-ingress-controller/
│   │   └── observability/          # Prometheus, Grafana, Pushgateway
│   └── applications/               # App deployments
│       └── load-harness/           # Deployment, Service, Ingress, Canary, HPA
│
├── policies/                       # Kyverno policies for CI validation
├── ops/                            # Operational scripts
├── docs/                           # Documentation
└── .github/workflows/              # CI/CD pipelines
```

---

## Technology Stack

### Infrastructure
| Component | Version | Purpose |
|-----------|---------|---------|
| EKS | 1.32 | Kubernetes control plane |
| Terraform | >= 1.14.0, < 2.0.0 | Infrastructure as Code |
| Flux | v2.7.3 | GitOps operator |
| Spot Instances | t3.large | Cost-optimized compute |

### Platform Services
| Component | Purpose |
|-----------|---------|
| nginx-ingress | Ingress controller + canary traffic splitting |
| cert-manager | Automated TLS certificates |
| Flagger | Progressive delivery / canary deployments |
| metrics-server | HPA scaling metrics |

### Observability
| Component | Purpose |
|-----------|---------|
| Prometheus | Metrics collection |
| Grafana | Dashboards and visualization |
| Pushgateway | DORA metrics collection |
| ServiceMonitors | Auto-discovery of scrape targets |

### CI/CD
| Component | Purpose |
|-----------|---------|
| GitHub Actions | Build, test, deploy pipelines |
| release-please | Automated versioning and changelogs |
| Dependabot | Dependency updates |
| Trivy | Container security scanning |
| Kyverno CLI | Policy validation in CI |

---

## Workflows

### On Every Push to Main

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Build &   │ → │   Trivy     │ → │   Push to   │ → │    Flux     │
│    Test     │    │    Scan     │    │     ECR     │    │   Syncs     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                                │
                                                                ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Canary    │ ← │   Flagger   │ ← │   Deploy    │ ← │   Image     │
│  Analysis   │    │   Creates   │    │   Canary    │    │ Automation  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Metrics Check: Success Rate > 99% && p99 Latency < 500ms          │
│  ✅ Pass → Promote to Primary                                       │
│  ❌ Fail → Automatic Rollback                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Scheduling

Both lifecycle workflows are **manual** (`workflow_dispatch`):

| Workflow | Purpose |
|----------|---------|
| `rebuild-stack.yml` | Provision the cluster |
| `nightly-destroy.yml` | Tear it down, to stop paying for it |
| `dora-metrics.yml` | Runs automatically after deployment workflows complete |

`nightly-destroy.yml` previously ran on a nightly cron. That trigger was
removed — a scheduled `terraform destroy` in a template someone else has
forked is a poor default. Re-enable it in your own copy by restoring the
`schedule:` trigger, and expect to pay for the cluster until you do.

---
## Cost Optimization

Roughly **$40-50/month** for the full stack left running continuously, in
`eu-west-2`. Your figures will differ by region and usage — treat the table as
illustrative, not a quote.

| Component | Monthly Cost |
|-----------|-------------|
| EKS Control Plane | $26.40 |
| NAT Gateway | $9.90 |
| EC2 Spot (t3.large) | $6.82 |
| **Total** | **~$43/month** |

### Cost Controls
- **Ephemeral staging** - destroy it when you are not using it (`nightly-destroy.yml`)
- **Spot instances** - 70% cheaper than on-demand
- **EKS 1.32** - Avoided $138/month extended support fees
- **nginx-ingress** - Free (vs ALB at $17/month)
- **Slim Flux** - Only essential controllers deployed

---

## Documentation

### Adopting this template
- **[CONFIGURATION.md](CONFIGURATION.md)** - every value you need to supply. Start here
- [Credentials-Free Template (DDR)](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md) - why this repository holds no secrets
- [GitHub OIDC Setup](docs/GITHUB-OIDC-SETUP.md) - AWS trust configuration
- [Terraform Cloud Setup](docs/TERRAFORM-CLOUD-SETUP.md) - HCP Terraform workspaces
- [SECURITY.md](SECURITY.md) - security policy and notes for forks
- [CONTRIBUTING.md](CONTRIBUTING.md) - how to contribute to the template

### Operating the platform
- [EKS Access Guide](docs/EKS-ACCESS.md) - reaching the cluster
- [GitOps Setup](docs/GITOPS-SETUP.md) - Flux configuration and CRD ordering
- [Progressive Delivery](docs/PROGRESSIVE-DELIVERY.md) - Flagger canary deployments
- [Canary Deployments](docs/CANARY-DEPLOYMENTS.md) - canary configuration
- [DORA Metrics](docs/DORA-METRICS.md) - metrics collection and dashboard
- [Monitoring Setup](docs/MONITORING-SETUP.md) - Prometheus and Grafana
- [TLS/SSL Setup](docs/TLS-SSL-SETUP.md) - certificate management
- [Stack Automation](docs/STACK-AUTOMATION.md) - destroy and rebuild
- [Cost Optimization](docs/COST-OPTIMIZATION-GUIDE.md) - what it costs and why

### Contributing to this template
- [Versioning Strategy](docs/VERSIONING-STRATEGY.md) - SemVer and release-please
- [Commit Messages](docs/COMMIT-MESSAGES.md) - conventional commits, enforced by CI
- [Dependabot](docs/DEPENDABOT.md) - dependency update policy
- [Local Workflow Testing](docs/ACT-LOCAL-TESTING.md) - running workflows with act

### Design records and project history
These document decisions and plans specific to the original project. They are
kept for the reasoning, not as instructions for adopters.
- [Terraform Cloud / EKS Access (DDR)](docs/TERRAFORM-CLOUD-EKS-DDR.md)
- [Multi-Environment Design](docs/MULTI-ENVIRONMENT-DESIGN.md)
- [Security Concerns](docs/SECURITY-CONCERNS.md) - audit findings and their status

---

## License

MIT — see [LICENSE](LICENSE).

The sample application, infrastructure code and documentation are all covered.
You are free to use this as the basis for your own platform, commercial or
otherwise.
