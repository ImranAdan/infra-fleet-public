# Infrastructure Fleet Documentation

This is the root documentation for the infra-fleet platform - a production-grade AWS EKS environment demonstrating modern cloud-native practices.

**Main README**: [../README.md](../README.md)

---

## Architecture

![Platform Architecture](ARCHITECTURE.png)

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
| **CI/CD** | Push → GitHub Actions → Build/Test → ECR → Flux Image Automation |
| **GitOps** | Manifest change → Flux detects → Applies to cluster |
| **Progressive Delivery** | New version → Flagger canary → Metrics analysis → Promote/Rollback |
| **User Traffic** | Users → Cloudflare → NLB → nginx-ingress → Application |
| **Observability** | Apps → Prometheus scrape → Grafana dashboards |

---

## Current Stack

| Component | Version/Type | Purpose |
|-----------|-------------|---------|
| EKS | 1.32 | Kubernetes control plane |
| Nodes | t3.large spot | Cost-optimized compute |
| Flux | v2.7.3 | GitOps operator |
| Flagger | Latest | Progressive delivery |
| nginx-ingress | Latest | Ingress + canary traffic |
| cert-manager | Latest | TLS certificates |
| Prometheus | kube-prometheus-stack | Metrics collection |
| Grafana | kube-prometheus-stack | Dashboards |

**Cost**: ~$43/month with ephemeral staging (destroyed nightly)

---

## Documentation Index

### Roadmaps
| Document | Description |
|----------|-------------|
| [Platform Build Roadmap](PLATFORM-BUILD-ROADMAP.md) | Infrastructure phases and status |
| [Release Engineering Roadmap](RELEASE-ENGINEERING-ROADMAP.md) | CI/CD maturity and practices |

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
| [Stack Automation](STACK-AUTOMATION.md) | Nightly destroy/rebuild |
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
| [Self-Hosted Runner](SELF-HOSTED-RUNNER.md) | GitHub Actions runner setup |
| [Security Concerns](SECURITY-CONCERNS.md) | Security considerations |

### Design Decisions
| Document | Description |
|----------|-------------|
| [Terraform Cloud EKS DDR](TERRAFORM-CLOUD-EKS-DDR.md) | Cluster access design |
| [Multi-Environment Design](MULTI-ENVIRONMENT-DESIGN.md) | Future multi-env architecture |

---

## Platform Status

### Completed Features
- [x] EKS 1.32 + Flux v2.7.3 GitOps
- [x] Progressive delivery (Flagger canary deployments)
- [x] TLS/HTTPS (cert-manager + Let's Encrypt + Cloudflare)
- [x] Dashboard UI (Flask + HTMX + Tailwind)
- [x] HPA autoscaling (metrics-server + HPA)
- [x] Prometheus + Grafana observability
- [x] DORA metrics collection and dashboard
- [x] release-please versioning
- [x] Dependabot dependency automation
- [x] Kyverno policy validation in CI

### In Progress
- [ ] GitOps Grafana dashboard provisioning (Issue #124)
- [ ] IAM least-privilege permissions (Issue #296)

### Planned
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

**Last Updated**: 2026-01-03
