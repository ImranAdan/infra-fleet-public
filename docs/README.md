# Infrastructure Fleet Documentation

This is the documentation for **Infrastructure Fleet**, a template for an AWS
EKS platform and the sample application — the Harness — that runs on it.

If you are adopting the template, start with
[../CONFIGURATION.md](../CONFIGURATION.md). This repository holds no
credentials and cannot deploy anything; see
[CREDENTIALS-FREE-TEMPLATE-DDR.md](CREDENTIALS-FREE-TEMPLATE-DDR.md).

**Main README**: [../README.md](../README.md)

> **On issue numbers.** Several documents cite issues and pull requests by
> number (`Issue #30`, `PR #31`). Those refer to the original project's tracker,
> not to this repository. They are kept as provenance for the reasoning; do not
> expect them to resolve here.

---

## Architecture

The diagram below is authoritative for the implemented topology. The older PNG
asset is retained only as project history; it shows an obsolete ALB path.

### Detailed Architecture Diagram

```
                                    ┌─────────────────────────────────────────────────────┐
                                    │                    GitHub                           │
                                    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
                                    │  │   Code      │  │  Workflows  │  │   Flux      │  │
                                    │  │   Push      │  │  (CI/CD)    │  │   Manifests │  │
                                    │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
                                    └─────────┼────────────────┼────────────────┼─────────┘
                                              │                │                │
                    ┌─────────────────────────┼────────────────┼────────────────┼─────────────────────────┐
                    │                         ▼                ▼                ▼                         │
                    │   AWS             ┌──────────┐    ┌─────────────┐   ┌──────────┐                    │
                    │                   │   ECR    │    │  Terraform  │   │   Flux   │                    │
                    │                   │  Images  │    │    Cloud    │   │  GitOps  │                    │
                    │                   └────┬─────┘    └──────┬──────┘   └────┬─────┘                    │
                    │                        │                 │               │                          │
                    │                        ▼                 ▼               ▼                          │
                    │   ┌────────────────────────────────────────────────────────────────────────────┐    │
                    │   │                              EKS Cluster                                   │    │
                    │   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │    │
                    │   │  │   Flagger   │  │   nginx     │  │ Prometheus  │  │  Grafana    │        │    │
                    │   │  │  (Canary)   │  │  ingress    │  │             │  │             │        │    │
                    │   │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────────────┘        │    │
                    │   │         │                │                │                                │    │
                    │   │         ▼                ▼                ▼                                │    │
                    │   │  ┌────────────────────────────────────────────────────────────────┐        │    │
                    │   │  │                    load-harness                                │        │    │
                    │   │  │   ┌─────────┐  ┌─────────┐  ┌─────────┐                        │        │    │
                    │   │  │   │ Primary │  │ Canary  │  │   HPA   │                        │        │    │
                    │   │  │   │  Pods   │  │  Pods   │  │ (1→8)   │                        │        │    │
                    │   │  │   └─────────┘  └─────────┘  └─────────┘                        │        │    │
                    │   │  └────────────────────────────────────────────────────────────────┘        │    │
                    │   └────────────────────────────────────────────────────────────────────────────┘    │
                    │                                      │                                              │
                    │                                      ▼                                              │
                    │                               ┌─────────────┐                                       │
                    │                               │     NLB     │                                       │
                    │                               └──────┬──────┘                                       │
                    └──────────────────────────────────────┼──────────────────────────────────────────────┘
                                                           │
                                                           ▼
                                                    ┌─────────────┐
                                                    │ Cloudflare  │
                                                    │     DNS     │
                                                    └──────┬──────┘
                                                           │
                                                           ▼
                                                    ┌─────────────┐
                                                    │    Users    │
                                                    │  (HTTPS)    │
                                                    └─────────────┘
```

### Key Flows

| Flow | Path |
|------|------|
| **CI/CD** | Release/Rebuild → GitHub Actions → Build/Test/Scan → ECR → Flux |
| **GitOps** | Manifest change → Flux detects → Applies to cluster |
| **Progressive Delivery** | New version → Flagger canary → Metrics analysis → Promote/Rollback |
| **User Traffic** | Users → Cloudflare → NLB → nginx-ingress → Application |
| **Observability** | Apps → Prometheus scrape → Grafana dashboards |

---

## Current Stack

| Component | Version/Type | Purpose |
|-----------|-------------|---------|
| EKS | 1.35 (`STANDARD` support) | Kubernetes control plane |
| Nodes | t3.large spot | Cost-optimized compute |
| Flux | v2.7.3 | GitOps operator |
| Flagger | 1.45.0 | Progressive delivery |
| nginx-ingress | 4.15.1 (retired; do not expose publicly) | Ingress + canary traffic |
| cert-manager | v1.21.1 | TLS certificates |
| Prometheus | kube-prometheus-stack | Metrics collection |
| Grafana | kube-prometheus-stack | Dashboards |

**Cost**: usage-based. Staging is destroyed manually, not nightly by default;
review current AWS pricing before deployment.

---

## Documentation Index
### Infrastructure
| Document | Description |
|----------|-------------|
| [Terraform Cloud Setup](TERRAFORM-CLOUD-SETUP.md) | Backend and workspace configuration |
| [GitHub OIDC Setup](GITHUB-OIDC-SETUP.md) | Secure CI/CD authentication |
| [EKS Access Guide](EKS-ACCESS.md) | Cluster access methods |
| [GitHub Environments](GITHUB-ENVIRONMENTS.md) | Environment protection rules |

### GitOps & Deployment
| Document | Description |
|----------|-------------|
| [GitOps Setup](GITOPS-SETUP.md) | Flux configuration, CRD ordering |
| [Progressive Delivery](PROGRESSIVE-DELIVERY.md) | Flagger canary deployments |
| [Canary Deployments](CANARY-DEPLOYMENTS.md) | Canary configuration and rollout |
| [Stack Automation](STACK-AUTOMATION.md) | Destroy and rebuild the ephemeral stack |
| [TLS/SSL Setup](TLS-SSL-SETUP.md) | Certificate management |

### Observability
| Document | Description |
|----------|-------------|
| [Monitoring Setup](MONITORING-SETUP.md) | Prometheus, Grafana, ServiceMonitors |
| [DORA Metrics](DORA-METRICS.md) | Engineering metrics collection |

### CI/CD & Development
| Document | Description |
|----------|-------------|
| [Versioning Strategy](VERSIONING-STRATEGY.md) | SemVer and release-please |
| [Commit Messages](COMMIT-MESSAGES.md) | Conventional commits |
| [Dependabot](DEPENDABOT.md) | Dependency automation |
| [Local Testing with act](ACT-LOCAL-TESTING.md) | Test workflows locally |

### Operations
| Document | Description |
|----------|-------------|
| [Cost Optimization Guide](COST-OPTIMIZATION-GUIDE.md) | Cost analysis and strategies |
| [Security Concerns](SECURITY-CONCERNS.md) | Security considerations |

### Design Decisions
| Document | Description |
|----------|-------------|
| [Credentials-Free Template DDR](CREDENTIALS-FREE-TEMPLATE-DDR.md) | Why this repository holds no secrets |
| [Terraform Cloud EKS DDR](TERRAFORM-CLOUD-EKS-DDR.md) | Cluster access design |
| [Multi-Environment Design](MULTI-ENVIRONMENT-DESIGN.md) | Future multi-env architecture |

---

## Included capabilities

### Implemented in the template
- [x] EKS 1.35 + Flux v2.7.3 GitOps
- [x] Progressive-delivery manifests (deployment preview; ingress migration required)
- [x] Optional TLS automation (deployment preview; ingress migration required)
- [x] Dashboard UI (Flask + HTMX + Tailwind)
- [x] HPA autoscaling (metrics-server + HPA)
- [x] Prometheus + Grafana observability
- [x] Ephemeral DORA proxy signals and dashboard JSON
- [x] release-please versioning
- [x] Dependabot dependency automation
- [x] Kyverno policy validation in CI

### Known follow-up work
- [ ] Replace retired ingress-nginx with a maintained Gateway API path
- [ ] GitOps Grafana dashboard provisioning (Issue #124)
- [ ] IAM least-privilege permissions (Issue #296)

### Possible extensions
- [ ] OIDC/SSO cluster access (Issue #92)
- [ ] Multi-environment architecture (Issue #264)

---

## Quick Links

### For Developers
- [Load Harness App](../applications/load-harness/README.md)
- [Local Development](../applications/load-harness/local-dev/)
- [Dashboard Design](../applications/load-harness/docs/dashboard-design.md)

### For Platform Engineers
- [Infrastructure Code](../infrastructure/)
- [GitOps Manifests](../k8s/)
- [CI/CD Workflows](../.github/workflows/)
- [Operational Scripts](../ops/)

### For Security
- [Kyverno Policies](../policies/)
- [Security Concerns](SECURITY-CONCERNS.md)

---

Operational guides above preserve some history from the source project. Treat
`CONFIGURATION.md` and the current workflows as authoritative when a historical
status or example conflicts with the template.
