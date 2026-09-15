<div align="center">

# Infra Fleet

**A staging Kubernetes platform template, with GitOps delivery, observable workloads, and an intent-driven advisor.**

Local Kubernetes or EKS · Flux GitOps · Kyverno admission policies · canary deployments with automatic rollback · Prometheus and Grafana

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.35-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Flux](https://img.shields.io/badge/GitOps-Flux%20v2.7.5-5468FF?logo=flux&logoColor=white)](https://fluxcd.io/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform&logoColor=white)](https://developer.hashicorp.com/terraform)
[![Use this template](https://img.shields.io/badge/Use%20this-template-2ea44f?logo=github)](https://github.com/ImranAdan/infra-fleet-public/generate)

[Try it locally](#try-it-locally-first) · [What you get](#what-you-get) · [Make it yours](CONFIGURATION.md) · [Docs](docs/README.md)

</div>

---

Infra Fleet is the platform template in the Infra Fleet project.
[Infra Fleet Advisor](https://github.com/ImranAdan/infra-fleet-advisor-public)
reviews its Git repository against declared security, reliability, and cost
intent and proposes evidenced recommendations for human review. The platform
works independently; the advisor evaluates versioned repository desired state.
See [connecting the advisor](docs/ADVISOR-INTEGRATION.md).

---

> **AWS deployment preview:** the AWS canary path still depends on the retired
> community `ingress-nginx` controller. Existing artifacts remain available,
> but upstream no longer ships bug or security fixes. Use the local path freely;
> do not expose a new public deployment until the planned Gateway API migration
> has been completed and validated through an apply, rollout, rollback, and
> destroy cycle. Local Kubernetes uses Envoy Gateway and Gateway API.

---

## Try it locally, first

Choose a [deployment profile](docs/DEPLOYMENT-PROFILES.md). Local Kubernetes runs
Flux, Kyverno, Flagger, Envoy Gateway and monitoring on kind, sharing application
resources and delivery controls with AWS staging.

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
cd infra-fleet-public
./fleet up --profile local
./fleet access --profile local --service app
```

See the guide for prerequisites, login credentials, acceptance checks and
teardown. For faster application-only development, use Docker Compose:

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
cd infra-fleet-public/applications/load-harness/local-dev
./dev.sh up-full
```

First run builds the image, so give it a few minutes; after that it is seconds.

Open **http://localhost:8080/ui** and press a button — the dashboard drives
real CPU and memory load, and you watch Prometheus and Grafana react to it live.

That is the same application the cluster runs, with the same app-level metrics
and dashboards. Kubernetes adds GitOps reconciliation, policy enforcement,
network isolation, autoscaling and canary delivery. If you like what you see,
the rest of this repository is an inspectable staging implementation—not a
production blueprint.

---

## What you get

Fork this and you have a platform that does the following, on day one:

| | |
|---|---|
| **Models staged delivery** | Choose local Kubernetes or AWS staging; Flux reconciles the selected profile and Flagger evaluates a canary. AWS routing remains a non-public preview |
| **Exposes useful signals** | Prometheus, Grafana and an explicitly heuristic DORA-signal pipeline for deployment events, lead time and failures |
| **Makes cost visible** | Spot instances, a slim Flux install, nginx ingress, and a manual teardown workflow for when you are not using it |
| **Proves itself in CI** | Both profiles rendered and checked, local Flux/Kyverno/canary behaviour exercised, Terraform and images scanned, commits linted |
| **Connects intent to improvement** | Infra Fleet Advisor evaluates declared positions against versioned repository evidence and proposes work for review |

---

## Current verification checkpoint

The local profile has completed a full disposable-cluster acceptance cycle.
Flux repaired deliberate drift, Kyverno rejected unsafe rollout and image
changes, Calico blocked an unauthorized namespace, Prometheus discovered the
application, and Flagger both promoted a healthy revision and rolled back a
forced failure. The authenticated application UI and API, Grafana health, and
the Prometheus target were also exercised through operator-facing commands.

CI renders and validates both deployment profiles, applies each profile's
admission policies, tests the application and container, and repeats the local
Kubernetes acceptance path. AWS staging has static coverage here; it still
requires an approved account-specific apply, rollout, rollback and destroy
cycle before anyone treats that route as deployment evidence.

The next review layer is the Advisor. It reads the merged repository revision,
opens a report PR, and waits for a human decision. Merging that report can then
publish eligible recommendations as fleet issues for separately selected fix
PRs. See [connecting the advisor](docs/ADVISOR-INTEGRATION.md) for the exact
handoff.

---

## Why this one

The platform gives you a concrete staging implementation to inspect, adapt,
and evaluate against your own priorities.

**It is testable, not just diagrammed.** CI checks the application, container,
Terraform and Kubernetes manifests without cloud access. A private copy adds
the live AWS and cluster checks. The sample application generates real load so
autoscaling, canary analysis and the dashboards have something useful to
measure.

**It admits that it costs money.** EKS, NAT, load balancing, storage, public
IPv4 and worker capacity are billed independently. The repository ships with
a destroy workflow because the most reliable cost control for a learning
environment is to turn it off when it is not being used.

**Intent guides the next improvement.** The advisor turns declared security,
reliability, and cost positions into deterministic evaluations. Recommendations
cite repository evidence; unsupported positions remain explicit coverage
gaps. You decide which proposals to accept.

---

## Make it yours

Click **Use this template** at the top of the repository, or:

```bash
gh repo create my-infra-fleet --private --template ImranAdan/infra-fleet-public
```

Use a private repository for your deployment configuration and operations.

Start with the [local profile](docs/DEPLOYMENT-PROFILES.md) using Docker, or
follow **[CONFIGURATION.md](CONFIGURATION.md)** for AWS staging. The AWS profile
needs an AWS account and HCP Terraform organisation; a first cluster build
commonly takes 25–40 minutes. A custom domain is optional.

The sample application is meant to be replaced. Doing so requires preserving
the Service, probe, metrics, image-automation, and canary contracts—not only
adding `/health` and `/metrics` endpoints. See
[replacing the Harness](applications/load-harness/docs/APPLICATION-ROADMAP.md#extending-or-replacing-the-harness).

---
## Architecture

```mermaid
flowchart TB
  Operator[Operator] --> Facade[./fleet --profile]
  Repo[Versioned fleet repository] --> CI[GitHub Actions]

  Facade -->|local| LocalBootstrap[kind + local registry<br/>read-only Git source]
  LocalBootstrap --> LocalFlux[Flux local cluster root]
  LocalFlux --> LocalPlatform[Envoy Gateway + Flagger<br/>Kyverno + monitoring]

  Facade -->|aws-staging| Workflows[Reviewed GitHub workflows]
  Workflows -->|OIDC| AWS[EKS + AWS infrastructure]
  Workflows --> ECR[ECR images]
  HCP[HCP Terraform<br/>state and locks] --- Workflows
  Repo --> AWSFlux[Flux AWS cluster root]
  ECR --> AWSFlux
  AWS --> AWSFlux
  AWSFlux --> AWSPlatform[NGINX staging route + Flagger<br/>Kyverno + monitoring]

  Shared[Shared application base<br/>and delivery contracts] --> LocalFlux
  Shared --> AWSFlux
  LocalPlatform --> App[Load Harness]
  AWSPlatform --> App

  Advisor[Infra Fleet Advisor] -->|reads merged revision| Repo
  Advisor --> ReportPR[Advisor report PR]
  ReportPR -->|human approval| FleetIssues[Fleet issues]
  FleetIssues -->|selected fixes| Repo
```

The facade is the profile boundary. Local commands do not invoke AWS or GitHub
writes. HCP Terraform stores AWS state and locks; Terraform execution and AWS
calls happen on the operator's machine or a GitHub-hosted runner.

**Key Flows:**
- **Local**: Committed revision → local registry and Git source → Flux → kind
- **AWS CI/CD**: Release/Rebuild → GitHub Actions → Build/Test/Scan → ECR → Flux → EKS
- **Progressive Delivery**: New version → Flagger canary → Traffic shifting → Metrics analysis → Promote/Rollback
- **Observability**: Applications → Prometheus scrape → Grafana dashboards → DORA metrics
- **Advisor**: Merged fleet revision → report PR → human approval → eligible fleet issues

See [docs/README.md](docs/README.md) for detailed architecture diagram.

---

## Key Features

### Progressive Delivery with Flagger

Automated canary deployments with metric-based promotion:

```yaml
# Canary configuration
analysis:
  interval: 30s
  threshold: 3         # Failed checks tolerated before rollback
  maxWeight: 50        # Max 50% traffic to canary
  stepWeight: 10       # 10% increments
  metrics:
    - name: workload-request-success-rate
      thresholdRange:
        min: 99        # Requires 99% success rate
    - name: workload-request-duration
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

Expose heuristic engineering-performance signals from workflow and cluster
events. These are useful for a lab dashboard, not a standards-compliant DORA
measurement system:

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
│       ├── tests/                  # Deterministic test suite
│       ├── monitoring/             # Grafana dashboards (JSON)
│       └── local-dev/              # Docker Compose dev environment
│
├── k8s/                            # GitOps manifests
│   ├── clusters/                   # Explicit local and AWS Flux roots
│   ├── profiles/                   # Provider-specific composition
│   ├── flux-system/                # Generated Flux controllers + AWS bootstrap
│   ├── infrastructure/             # Shared Helm releases and namespaces
│   │   ├── cert-manager/           # TLS certificates
│   │   ├── flagger/                # Progressive delivery
│   │   ├── nginx-ingress-controller/
│   │   └── observability/          # Prometheus, Grafana, Pushgateway
│   └── applications/               # Shared application resources
│       └── load-harness/           # Deployment, Service, Canary, HPA, policy
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
| EKS | 1.35 | Kubernetes control plane |
| Terraform | >= 1.14.0, < 2.0.0 | Infrastructure as Code |
| Flux | v2.7.5 local / v2.7.3 AWS | GitOps operator |
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
| PodMonitors / ServiceMonitors | Auto-discovery of scrape targets |

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

### On a release or manual rebuild

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
forked is a poor default. An adopter who adds a schedule owns its timing,
approval, and failure-notification design.

---
## Cost Optimization

This stack creates billable AWS resources. At the currently published
[AWS EKS price](https://aws.amazon.com/eks/pricing/), a control plane under
standard version support alone is `$0.10` per cluster-hour. NAT
gateway time and data, Spot nodes, load balancing, storage and public IPv4 are
additional and vary by region and use. Check current AWS pricing and set an AWS
Budget before applying the stack.

The manual destroy workflow removes the ephemeral staging resources. It does
not remove the permanent ECR repository or IAM resources, and it is not
scheduled by default.

### Cost Controls
- **Ephemeral staging** - destroy it when you are not using it (`nightly-destroy.yml`)
- **Spot instances** - variable discounts in exchange for interruption risk
- **EKS 1.35 with `STANDARD` support** - prevents accidental extended-support billing
- **Manual teardown** - removes hourly staging resources when the lab is idle
- **Slim Flux** - Only essential controllers deployed

---

## Documentation

### Adopting this template
- **[CONFIGURATION.md](CONFIGURATION.md)** - every value you need to supply. Start here
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
- [Template Deployment Boundaries (DDR)](docs/PUBLIC-TEMPLATE-BOUNDARY-DDR.md)
- [Multi-Environment Design](docs/MULTI-ENVIRONMENT-DESIGN.md)
- [Security Concerns](docs/SECURITY-CONCERNS.md) - audit findings and their status

---

## License

MIT — see [LICENSE](LICENSE).

The sample application, infrastructure code and documentation are all covered.
You are free to use this as the basis for your own platform, commercial or
otherwise.
