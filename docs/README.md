# Infra Fleet Documentation

Choose [local Kubernetes or AWS staging](DEPLOYMENT-PROFILES.md). The profiles
share application resources and delivery controls; their provisioning,
networking and registry restrictions are explicit.

This is the documentation for **Infra Fleet**, a template for local Kubernetes
or an AWS EKS platform and the contract-defined applications that run on it.

The application is a plug-in: see the [application contract](APPLICATION-CONTRACT.md)
to swap Load Harness for another app.

If you are adopting the template, start with
[../CONFIGURATION.md](../CONFIGURATION.md). For repository review and
recommendation delivery, see [Advisor Integration](ADVISOR-INTEGRATION.md).

**Main README**: [../README.md](../README.md)

> Design records and the security audit retain dated findings for provenance.
> Their status blocks identify superseded behavior; the operating guides and
> current manifests are authoritative.

---

## Architecture

[Architecture](ARCHITECTURE.md) walks through the platform one flow at a time,
each with its own small diagram: profiles, AWS onboarding, GitOps delivery,
progressive delivery, request paths, observability and guardrails.

### Key Flows

| Flow | Path |
|------|------|
| **Fast CI** | Pull request → render/test/scan → intent gate → exact-head merge gate |
| **Local acceptance** | Weekly or manual dispatch → kind cluster per app → promote/rollback → teardown |
| **Local GitOps** | Committed snapshot → read-only local Git source → Flux → kind |
| **AWS CI/CD** | Release/Rebuild → GitHub Actions → Build/Test/Scan → ECR → Flux |
| **AWS GitOps** | Manifest change → Flux detects → applies to EKS |
| **Progressive Delivery** | New version → Flagger canary → Metrics analysis → Promote/Rollback |
| **User Traffic** | Loopback → Envoy Gateway → local application, or users → Cloudflare → NLB → AWS preview |
| **Local Control Plane** | Contracts → bounded Flux launch objects → on-demand application stacks |
| **Observability** | Gateway, kubelet and apps → Prometheus → Grafana dashboards |

---

## Current Stack

| Component | Version/Type | Purpose |
|-----------|-------------|---------|
| EKS | 1.35 (`STANDARD` support) | Kubernetes control plane |
| Nodes | t3.large spot, 1–3 via cluster-autoscaler | Released outside the weekday usage window |
| Flux | v2.7.5 local / v2.7.3 AWS | GitOps operator |
| Flagger | 1.45.0 | Progressive delivery |
| Envoy Gateway | 1.9.1 | Gateway API routing (HTTPS only) + canary traffic, both profiles |
| cert-manager | v1.21.1 | TLS certificates (local CA locally, Let's Encrypt on AWS) |
| Prometheus | kube-prometheus-stack | Metrics collection |
| Grafana | kube-prometheus-stack | Dashboards |

**Cost**: usage-based. Workers are released outside the weekday usage window;
the stack itself is destroyed only manually. Review current AWS pricing first.

---

## Documentation Index
### Infrastructure
| Document | Description |
|----------|-------------|
| [Terraform Cloud Setup](TERRAFORM-CLOUD-SETUP.md) | Backend and workspace configuration |
| [GitHub OIDC Setup](GITHUB-OIDC-SETUP.md) | Secure CI/CD authentication |
| [EKS Access Guide](EKS-ACCESS.md) | Cluster access methods |
| [GitHub Environments](GITHUB-ENVIRONMENTS.md) | Local and AWS deployment records, gates and protection rules |

### GitOps & Deployment
| Document | Description |
|----------|-------------|
| [GitOps Setup](GITOPS-SETUP.md) | Flux configuration, CRD ordering |
| [Progressive Delivery](PROGRESSIVE-DELIVERY.md) | Flagger canary deployments |
| [Canary Deployments](CANARY-DEPLOYMENTS.md) | Canary configuration and rollout |
| [Stack Automation](STACK-AUTOMATION.md) | Destroy and rebuild the ephemeral stack |
| [Local Kubernetes](LOCAL-KUBERNETES.md) | The kind profile and its acceptance workflow |
| [Deployment Profiles](DEPLOYMENT-PROFILES.md) | Local and AWS lifecycle, access and verification boundary |
| [TLS and DNS](TLS-SSL-SETUP.md) | Gateway certificates and the optional public hostname |

### Observability
| Document | Description |
|----------|-------------|
| [Monitoring Setup](MONITORING-SETUP.md) | Gateway and container signals, dashboards provisioned from Git |
| [Application Contract](APPLICATION-CONTRACT.md) | What an app brings, what the platform provides, and how to swap it |
| [Application Control Plane](APPLICATION-CONTROL-PLANE.md) | Launch and stop contracted apps locally; trust and failure boundaries |
| [DORA Metrics](DORA-METRICS.md) | Engineering metrics collection |

### CI/CD & Development
| Document | Description |
|----------|-------------|
| [Dependabot](DEPENDABOT.md) | Dependency automation |
| [Local Testing with act](ACT-LOCAL-TESTING.md) | Test workflows locally |

### Operations
| Document | Description |
|----------|-------------|
| [Advisor Integration](ADVISOR-INTEGRATION.md) | Run static reviews and understand the delivery contract |
| [Rollout Capacity](ROLLOUT-CAPACITY.md) | Zero-unavailable rollout contract and the Flux controller exception |
| [Template Readiness](TEMPLATE-READINESS.md) | Current evidence, limits and the remaining AWS acceptance cycle |
| [AWS Cost Controls](COST-OPTIMIZATION-GUIDE.md) | Billable resources, worker schedule, teardown and audit controls |
| [Security Concerns](SECURITY-CONCERNS.md) | Security considerations |

### Design Decisions
| Document | Description |
|----------|-------------|
| [Deployment Profiles DDR](DEPLOYMENT-PROFILES-DDR.md) | Local/AWS strategy boundary, shared contracts and deployment gates |
| [Template Deployment Boundaries DDR](PUBLIC-TEMPLATE-BOUNDARY-DDR.md) | Template adoption and deployment architecture |
| [Terraform Cloud EKS DDR](TERRAFORM-CLOUD-EKS-DDR.md) | Cluster access design |
| [Multi-Environment Design](MULTI-ENVIRONMENT-DESIGN.md) | Deferred production-promotion constraints and open decisions |

---

## Included capabilities

### Implemented in the template
- [x] Local Kubernetes or EKS 1.35 with Flux GitOps
- [x] Envoy Gateway progressive delivery, live-tested locally
- [x] cert-manager TLS: local CA for `*.apps.localhost`, Let's Encrypt on AWS (preview)
- [x] Local application dashboard: launch and stop any contracted app on demand
- [x] Dashboard UI (Flask + HTMX + Tailwind)
- [x] HPA autoscaling, plus AWS cluster-autoscaler and a weekday worker window
- [x] Prometheus + Grafana observability
- [x] Ephemeral DORA proxy signals and dashboard JSON
- [x] release-please versioning
- [x] Dependabot dependency automation
- [x] Kyverno policies in CI and at admission
- [x] Intent gate, exact-head merge gate and opt-in autonomous merge

### Known follow-up work
- [x] Replace retired ingress-nginx in the AWS profile with a maintained Gateway API path
- [ ] Live-cycle test the AWS Gateway route (apply, Let's Encrypt, canary, teardown)
- [ ] Validate the remaining IAM permissions-boundary design in a real AWS lifecycle

### Possible extensions
- [ ] OIDC/SSO cluster access
- [ ] Multi-environment architecture; constraints are recorded in [Multi-environment design](MULTI-ENVIRONMENT-DESIGN.md)

---

## Quick Links

### For Developers
- [Load Harness](../applications/load-harness/README.md), [podinfo](../applications/podinfo/README.md), [Fleet Runner](../applications/mario-game/README.md)
- [Local Development](../applications/load-harness/local-dev/)

### For Platform Engineers
- [Infrastructure Code](../infrastructure/)
- [GitOps Manifests](../k8s/)
- [CI/CD Workflows](../.github/workflows/)
- [Operational Scripts](../ops/)

### For Security
- [Kyverno Policies](../policies/)
- [Security Concerns](SECURITY-CONCERNS.md)

---

Treat `CONFIGURATION.md`, the profile guides and current workflows as
authoritative when a dated design or audit record describes superseded behavior.
