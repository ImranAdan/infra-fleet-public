# Platform Build Roadmap

## Vision Statement

Build a modern, cloud-native platform that enables rapid application development and deployment while maintaining operational excellence. The platform follows a multi-stakeholder approach where developers, DevOps engineers, and platform engineers can work efficiently without blocking each other.

## Current State

### ✅ Infrastructure Foundation (Completed)
- **EKS Cluster** in `infrastructure/staging/`
  - 2-AZ deployment (eu-west-2a, eu-west-2b)
  - Public API endpoint (0.0.0.0/0) with IAM authentication
  - Session Manager disabled (cost optimization)
  - Spot instances for ~70% cost savings
  - Single worker node (t3.large spot, 35 pod max)
  - Hybrid networking (NAT Gateway only - S3 endpoint removed as redundant)
  - Cost-optimized at ~$15-20/month with nightly destroy
  - **Note**: Single node = planned downtime during updates (acceptable for dev/learning)

- **Network Architecture**
  - VPC with public/private subnets
  - Single NAT Gateway for cost optimization
  - NAT Gateway provides S3 access (dedicated endpoint removed - was creating Interface instead of Gateway)

- **Pod Capacity** (t3.large = 35 pods max)
  - Current usage: 15/17 pods (2 slots buffer)
  - kube-system: 5 pods (coredns, aws-node, kube-proxy, ebs-csi, pod-identity)
  - flux-system: 5 pods (source, kustomize, helm, image-reflector, image-automation)
  - observability: 4 pods (prometheus, grafana, operator, kube-state-metrics)
  - applications: 1 pod (load-harness)

### ✅ Application Foundation (Completed)
- **Load Harness Application** in `applications/load-harness/`
  - Proper Python project structure (`src/`, `tests/`)
  - Docker-first development with hot reload
  - Containerized testing approach
  - Basic CI pipeline for validation
  - Configurable via environment variables

## Stakeholder Separation of Concerns

### 👩‍💻 Developer Experience
**Focus**: Fast feedback loops and productive local development

**Responsibilities**:
- Application code development
- Local testing and debugging
- Feature implementation
- Unit and integration tests

**Tools & Workflow**:
- `docker-compose up --build` for local development
- Hot reload for immediate feedback
- `docker-compose --profile test run test` for testing
- Git feature branch workflow
- No infrastructure concerns

### 🔧 DevOps Engineer
**Focus**: CI/CD pipelines and deployment automation

**Responsibilities**:
- GitHub Actions CI/CD pipelines
- Container image building and publishing
- GitOps repository management
- Deployment orchestration
- Release management

**Tools & Workflow**:
- GitHub Actions for CI/CD
- ECR for container registry
- Flux for GitOps deployments
- Automated testing gates
- Promotion workflows

### 🏗️ Platform Engineer  
**Focus**: Infrastructure, observability, and platform services

**Responsibilities**:
- Kubernetes cluster management
- Infrastructure as Code (Terraform)
- Observability stack deployment
- Security and compliance
- Platform service development

**Tools & Workflow**:
- Terraform for infrastructure
- Kubernetes for orchestration
- Prometheus/Grafana for monitoring
- Service mesh considerations
- Platform API development

## Phase 1: Foundation ✅ COMPLETE

### 🎯 Goals (All Achieved)
- ✅ Establish basic CI/CD workflow
- ✅ Create container registry infrastructure
- ✅ Implement GitOps pattern
- ✅ Deploy first application to EKS

### 📋 Tasks

#### 1.1 Container Registry Setup
- [x] Create ECR repository for load-harness
- [x] Configure IAM permissions for GitHub Actions
- [x] Update CI pipeline to push to ECR
- [x] Implement image vulnerability scanning

#### 1.2 GitOps Repository
- [x] Structure Kubernetes manifests (using `k8s/` directory)
- [x] Configure Flux in EKS cluster (CLI bootstrap via rebuild-stack.yml)
- [x] Implement automatic deployments (Flux kustomizations)
- [x] Resolved Flux race condition during destroy (PR #31)
- [x] Fixed Flux SSH authentication on destroy (PR #32)

#### 1.3 Version Management & Cost Control
- [x] Upgrade to Kubernetes 1.32 (avoid extended support charges)
- [x] Upgrade to Flux v2.7.3 (K8s 1.32 compatibility)
- [x] Document version upgrade process and timeline
- [x] Set quarterly EKS version check reminder (February 2026)
- [x] Comprehensive cost optimization guide

**Key Learning**: Kubernetes versions enter extended support 14 months after release at 6× cost ($0.60/hr vs $0.10/hr). Timely upgrades critical for cost control.

**Version Timeline**:
- K8s 1.29: Extended support began March 2025 (we upgraded Nov 2025)
- K8s 1.32: Standard support until ~March 2026
- Next upgrade: Target February 2026 → K8s 1.33

#### 1.4 Basic Observability ✅ COMPLETE
- [x] Deploy Prometheus to EKS cluster (kube-prometheus-stack via Flux HelmRelease)
- [x] Configure basic application metrics collection (ServiceMonitor for load-harness)
- [x] Create initial Grafana dashboards (CPU utilization, request metrics)
- [x] Implement health check monitoring (Prometheus targets auto-discovery)

**Deployed Components** (PR #112, #128):
- Prometheus Server (ephemeral storage, 2-day retention)
- Prometheus Operator (TLS disabled for simplicity)
- Grafana with load-harness dashboard
- kube-state-metrics for K8s object metrics
- ServiceMonitor for automatic Flask metrics scraping

**Key Decision**: No Ingress for observability stack - port-forward access only. This eliminates ALB finalizer issues during destroy and keeps costs down.

#### 1.5 Application Load Balancer ⏸️ PAUSED (Cost Optimization)
- [x] Deploy AWS Load Balancer Controller (via Flux HelmRelease)
- [x] Configure Ingress for load-harness (with IP whitelisting)
- [x] Resolved ALB controller credentials issue (Pod Identity restart)
- [x] Implemented cleanup script for orphaned ALBs (PR #29)
- [ ] Set up DNS and SSL certificates
- [ ] Test external application access

**Status**: ALB controller **disabled** (PR #156) to save ~$17-18/month.
**Reason**: Port-forward access sufficient for dev/learning. ALB adds significant cost (~$16.20/month when running 24/7) with no current need for external access.
**Re-enable when**: External access is genuinely required (demo, integration testing with external services).

**Architectural Decision: Infrastructure vs Application Resources**

When implementing the ALB controller, we chose to split resource management:
- **Terraform manages AWS resources**: IAM roles, policies, Pod Identity associations
- **Flux manages Kubernetes resources**: Helm charts, HelmReleases, Ingress resources

**Options Considered**:

**Option A: Terraform Helm Provider**
- Terraform installs Helm charts directly to cluster
- Pros: Single tool, no additional Flux controllers needed
- Cons: Not GitOps-managed, Terraform needs cluster access, K8s resources in Terraform state

**Option B: Flux HelmRelease (GitOps) ✅ CHOSEN**
- Flux helm-controller manages Helm charts
- Pros: True GitOps, K8s tools manage K8s, faster iterations, cleaner separation
- Cons: Requires helm-controller (+1 pod)

**Decision**: We chose **Option B** for these reasons:
1. **Separation of concerns**: Infrastructure (Terraform) vs workloads (Flux)
2. **GitOps principle**: All K8s resources visible in Git, not hidden in Terraform
3. **Faster iterations**: Change K8s resources without Terraform apply cycles
4. **Team scalability**: Platform team manages AWS, DevOps manages K8s deployments
5. **Simpler Terraform state**: Less K8s resources in Terraform state = faster, safer applies
6. **Future-proof**: Pattern extends to observability (Prometheus, Grafana), databases, etc.

**Trade-off Accepted**: helm-controller is part of the default Flux installation (already running), so no additional pod cost. The ALB controller itself adds +1 pod (9/11 → 10/11 pods). This is acceptable for dev/staging and provides the foundation for future Helm-based deployments (Prometheus, Grafana).

## Phase 2: Enhanced Developer Experience

### 🎯 Goals
- Streamline developer workflows
- Implement self-service capabilities
- Add comprehensive testing strategies
- Enhance local development tools

### 📋 Tasks

#### 2.1 Enhanced CI/CD
- [ ] Multi-stage pipeline (test → build → deploy)
- [ ] Integration testing in CI
- [ ] Security scanning (container & code)
- [ ] Automated rollback capabilities

#### 2.4 Image Deployment Strategy ✅ UPGRADED TO GITOPS
**Current Approach**: Flux Image Automation (PR #146) ✅ IMPLEMENTED
- ✅ CI builds image and pushes to ECR with SemVer tags (e.g., `v1.2.3`)
- ✅ Flux image-reflector-controller scans ECR for new images
- ✅ Flux image-automation-controller commits manifest updates to Git
- ✅ CI has NO write access to deployment manifests (security boundary)
- ✅ Eliminates CI race conditions when concurrent PRs merge

**Architecture**:
```
CI Pipeline:     git tag (v1.2.3) → build → push ECR → DONE
Flux Automation: scan ECR → select highest semver → commit to git → sync cluster
```

**Tag Strategy**: SemVer with `v` prefix (e.g., `v1.2.3`)
- ImagePolicy filters tags matching `^v[0-9]+\.[0-9]+\.[0-9]+$`
- SemVer ordering ensures highest version is selected
- Integrated with release-please for automated versioning

**Components Deployed**:
- `image-reflector-controller` - Scans ECR repositories
- `image-automation-controller` - Commits manifest updates
- Pod Identity association for ECR access (PR #160 fixed ordering)

#### 2.2 LoadHarness Dashboard UI ✅ COMPLETE
**Goal**: Web-based dashboard for triggering load tests and visualizing results without Grafana access.

**Design Doc**: `applications/load-harness/docs/dashboard-design.md`

**Tech Stack**: Flask + Jinja2 + HTMX + Tailwind CSS (no new deployments)

**Implementation** (~2,200 lines of code):
- `src/load_harness/dashboard/routes.py` - All dashboard routes
- `templates/dashboard.html` - Main UI with forms
- `templates/partials/` - HTMX partial templates
- `templates/base.html` - Layout with Tailwind + HTMX

**Phases**:
- [x] Phase 1: Project foundation (dashboard shell at `/ui`)
- [x] Phase 2: Load test forms (CPU, Memory, Cluster Load)
- [x] Phase 3: Job management panel (client-side tracking with localStorage)
- [x] Phase 4: Live metrics (Prometheus integration with per-pod metrics)
- [x] Phase 5: Polish & error handling (dark mode, responsive design, error states)

**Features Implemented**:
- All 3 load test types (CPU, Memory, Cluster)
- Prometheus integration with live metrics refresh
- HTMX-powered dynamic updates
- Dark mode with localStorage persistence
- Authentication system
- Per-pod CPU/memory visualization
- Client-side job tracking

#### 2.3 Local Development Enhancements
- [ ] Local Kubernetes development (k3d/kind)
- [ ] Database integration for local dev
- [ ] Service mocking capabilities
- [ ] Development environment parity

#### 2.5 Testing Strategy
- [ ] Unit testing framework expansion
- [ ] Integration testing with test containers
- [ ] End-to-end testing pipeline
- [ ] Performance testing baseline

#### 2.6 Horizontal Pod Autoscaling ✅ COMPLETE
**Goal**: Enable automatic scaling of load-harness based on CPU utilization.

**Implementation**:
- ✅ **metrics-server**: Deployed as EKS managed addon (`infrastructure/staging/eks.tf`)
- ✅ **HPA**: Configured for load-harness (`k8s/applications/load-harness/hpa.yaml`)

**HPA Configuration**:
- Min replicas: 1 (cost-optimized idle state)
- Max replicas: 8 (respects t3.large pod capacity)
- Scale-up: Immediate (0s stabilization)
- Scale-down: Conservative (60s stabilization)
- Target: 50% CPU utilization

**Note**: metrics-server uses EKS managed addon (cleaner than Helm chart approach).

## Phase 3: Production Readiness

### 🎯 Goals
- Multi-environment support
- High availability and zero-downtime deployments
- Production-grade observability
- Security hardening
- Disaster recovery planning

### 📋 Tasks

#### 3.1 High Availability & Service Reliability
**Current State**: Single worker node (acceptable for dev/staging)
- ✅ Cost-optimized with spot instances (~$41/month)
- ✅ Nightly rebuild for learning/testing
- ⚠️ Planned downtime during node updates (~5-10 minutes)
- ⚠️ No pod redundancy (single point of failure)

**Production Requirements**:
- [ ] **Multi-node cluster** (minimum 2 nodes for HA)
  - Enables zero-downtime deployments
  - Node failures don't cause outages
  - Rolling updates without service interruption
  - Cost: +$6/month for 2-node spot setup
- [ ] **Pod Disruption Budgets (PDB)** for critical services
  - Prevents full service outages during drains
  - Enforces minimum availability requirements
- [ ] **Multi-replica deployments** for applications
  - Minimum 2 replicas for user-facing services
  - Anti-affinity rules (spread across nodes)
- [ ] **Node group upgrade strategy**
  - Blue/green node groups for zero-downtime updates
  - Automated node rotation schedules
- [ ] **Cluster autoscaling** (optional)
  - ✅ Horizontal pod autoscaling (HPA) - implemented for load-harness
  - Cluster autoscaler for dynamic node scaling (not needed for single-node)

**Migration Path**:
1. **Phase 3a**: 2-node spot cluster (~$47/month)
   - Zero-downtime deployments
   - Good for staging/pre-prod
2. **Phase 3b**: 2 on-demand + 1 spot (~$80-90/month)
   - Production-grade reliability
   - Cost optimization with spot
3. **Phase 3c**: Multi-AZ with autoscaling (~$150-200/month)
   - Full HA across availability zones
   - Dynamic scaling based on load

#### 3.2 Multi-Environment Architecture
- [ ] Production EKS cluster
- [ ] Environment-specific configurations
- [ ] Blue-green deployment strategy
- [ ] Canary deployment capabilities

#### 3.3 Advanced Observability
- [ ] Distributed tracing (Jaeger/OpenTelemetry)
- [ ] Log aggregation and correlation
- [ ] Custom business metrics
- [ ] Alerting and incident response

#### 3.4 Security & Compliance
- [ ] Pod Security Standards implementation
- [ ] Network policies enforcement
- [ ] Secrets management with External Secrets
- [ ] Compliance scanning and reporting

## Phase 4: Platform Maturity

### 🎯 Goals
- Self-service platform capabilities
- Advanced automation
- Multi-tenancy support
- Platform API development

### 📋 Tasks

#### 4.1 Platform Services
- [ ] Service catalog development
- [ ] Template-based application onboarding
- [ ] Resource quotas and governance
- [ ] Cost allocation and chargeback

#### 4.2 Advanced Features
- [ ] Service mesh implementation (Istio/Linkerd)
- [ ] Advanced traffic management
- [ ] Chaos engineering practices
- [ ] Performance optimization

## Technology Stack

### Core Infrastructure
- **Cloud Provider**: AWS
- **Container Orchestration**: Amazon EKS (Kubernetes 1.32)
- **Infrastructure as Code**: Terraform
- **Networking**: VPC with private/public subnets

### CI/CD & GitOps
- **Version Control**: GitHub
- **CI/CD**: GitHub Actions
- **Container Registry**: Amazon ECR
- **GitOps**: Flux v2.7.3
- **Deployment Strategy**: Rolling updates → Blue-Green → Canary

### Observability Stack
- **Metrics**: Prometheus + Grafana
- **Logging**: Fluent Bit → CloudWatch/ELK
- **Tracing**: OpenTelemetry → Jaeger
- **Alerting**: AlertManager → PagerDuty/Slack

### Development Tools
- **Local Development**: Docker + Docker Compose
- **Testing**: pytest + testcontainers
- **Code Quality**: SonarQube/CodeQL
- **Security**: Trivy, Snyk, OPA Gatekeeper

## Success Metrics

### Developer Productivity
- **Deployment frequency**: Target daily deployments
- **Lead time**: < 1 hour from commit to production
- **Mean time to recovery**: < 30 minutes
- **Change failure rate**: < 5%

### Platform Reliability
- **Uptime (Dev/Staging)**: Best effort with planned downtime windows
- **Uptime (Production)**: 99.9% availability SLA (requires multi-node HA)
- **Performance**: < 200ms p95 response time
- **Scalability**: Auto-scaling from 2-50 pods
- **Cost efficiency**: Track cost per transaction
- **Zero-downtime deployments**: Production requirement (needs 2+ nodes)

### Team Efficiency
- **Onboarding time**: New developer productive in < 4 hours
- **Self-service adoption**: 90% of deployments automated
- **Incident reduction**: 50% fewer platform-related incidents
- **Knowledge sharing**: Comprehensive documentation and runbooks

## Cost Optimization Learnings

### Biggest Cost Levers (By Impact)

**1. Version Management** ($1,656/year savings)
- Kubernetes extended support costs 6× standard pricing
- Timely upgrades essential (14-month lifecycle before extended support)
- Quarterly version checks recommended (calendar reminder February 2026)

**2. Operational Discipline** (~$20-26/month potential savings)
- Manual destruction at end of day vs relying on scheduled destroy
- Every hour after work = $0.172
- Shell aliases make destruction frictionless: `cluster-stop`

**3. Uptime Pattern** (Achieved ~80% reduction)
- From 24/7 ($88/month) to ~$15-20/month with nightly destroy
- Nightly destruction at 8 PM UTC + manual triggers
- Hourly rate when running: $0.172/hour

**4. Infrastructure Choices** (Implemented)
- Spot instances: ~70% EC2 savings (~$2.77/month)
- Single NAT Gateway: Flexibility for app internet access
- Session Manager disabled: $10-15/month savings
- Flux with image automation: 5 controllers (source, kustomize, helm, image-reflector, image-automation)

**5. Resource Cleanup** (~$17/month ALB savings)
- Flux suspension during destroy prevents race condition
- Cleanup script prevents orphaned resources (ALBs, EBS, security groups)
- Critical for ephemeral infrastructure pattern

### Cost Anti-Patterns Avoided

❌ **VPC Endpoints Only**: Would limit future application flexibility for minimal savings
❌ **Fargate for System Workloads**: Complex for minimal benefit (~$1-2/month)
❌ **Smaller Instance Types**: t3.small is minimum for reliable CoreDNS operation
❌ **Ignoring Version Management**: Extended support would cost more than all other optimizations combined

### Future Cost Considerations

- **ALB re-enablement**: +$17-18/month when running (currently disabled - PR #156)
- **Metrics-server for HPA**: +1 pod slot (minimal cost impact)
- **Multi-node HA**: +$6/month (2-node spot, when production-ready)

## Risk Mitigation

### Technical Risks
- **Vendor lock-in**: Use cloud-agnostic tools where possible
- **Complexity creep**: Maintain simple, documented solutions
- **Security vulnerabilities**: Automated scanning and updates
- **Performance degradation**: Continuous monitoring and testing
- **Single node downtime**: Acceptable for dev/staging, requires multi-node for production
- **Spot instance interruptions**: Acceptable risk for cost savings in non-prod environments
- **Version drift**: Quarterly EKS version checks prevent extended support charges

### Organizational Risks
- **Skill gaps**: Training programs and documentation
- **Resistance to change**: Incremental adoption and quick wins
- **Resource constraints**: Phased implementation approach
- **Communication gaps**: Regular stakeholder meetings and updates

## Next Immediate Actions

### ✅ Phase 1 Complete
1. ✅ **Create ECR repository** for load-harness application
2. ✅ **Set up GitHub repository** and push application code
3. ✅ **Test CI pipeline** with container build and push
4. ✅ **Install Flux** in EKS cluster for automated deployments
5. ✅ **Deploy AWS Load Balancer Controller** (now disabled for cost - PR #156)
6. ✅ **Implement nightly destroy/rebuild automation** (cost optimization)
7. ✅ **Upgrade to Kubernetes 1.32 + Flux v2.7.3** (avoid extended support charges)
8. ✅ **Create comprehensive cost optimization guide** (analysis and strategies)
9. ✅ **Set up basic observability** (Prometheus + Grafana - PR #112, #128)
10. ✅ **Implement Flux Image Automation** (PR #146 - eliminates CI race conditions)

### ✅ Recently Completed (Phase 2)
1. ✅ **LoadHarness Dashboard UI** - Complete with all 5 phases implemented
2. ✅ **metrics-server + HPA** - EKS addon + HPA for load-harness
3. ✅ **HTTPS/TLS** - cert-manager + Let's Encrypt + Cloudflare DNS
4. ✅ **Progressive Delivery** - Flagger canary deployments with nginx-ingress
5. ✅ **DORA Metrics** - Pushgateway + Grafana dashboard

### 🔄 Current Focus
1. 🔄 **GitOps dashboard provisioning** (Issue #124) - dashboards survive nightly rebuilds
2. 🔄 **Security hardening** (Issue #296, #92) - IAM least-privilege, OIDC/SSO

### ⏸️ Paused (Cost/Priority)
- **Multi-environment** (Issue #264) - designed, deferred for cost
- **Gateway API migration** (Issue #294) - future consideration

## Recent Completed Work

### 2026-01 Summary
- ✅ TLS/HTTPS with cert-manager + Let's Encrypt + Cloudflare DNS
- ✅ Flagger progressive delivery with nginx-ingress canary deployments
- ✅ DORA metrics collection and Grafana dashboard
- ✅ LoadHarness Dashboard UI (all 5 phases complete)
- ✅ ProxyFix middleware for HTTPS session cookies (v1.5.3)
- ✅ Various CI workflow fixes (bake time, Pushgateway checks)

### 2025-12 Summary
- ✅ Flux Image Automation with SemVer tags (PR #146)
- ✅ Pod Identity ordering fix for image-reflector-controller (PR #160)
- ✅ Pod capacity optimization: 15/17 pods with 2 slots buffer (PR #147)
- ✅ Cost optimization: orphaned EIP cleanup, S3 endpoint removal

### 2025-11 Summary
- ✅ EKS 1.32 + Flux v2.7.3 upgrade ($1,656/year savings)
- ✅ Prometheus + Grafana observability stack (PR #112, #128)
- ✅ Nightly destroy/rebuild automation
- ✅ Hybrid cleanup approach for orphaned resources (Issue #69)

### Outstanding Issues (6 open)

**Security** (High Priority):
- Issue #296: Scope IAM permissions from wildcards to least-privilege
- Issue #92: Replace IAM user cluster access with OIDC/SSO authentication

**Infrastructure** (Medium Priority):
- Issue #238: Move permanent resources to aws-account-core
- Issue #124: Implement GitOps-managed Grafana dashboard provisioning

**Future Enhancements** (Low Priority):
- Issue #264: Multi-environment architecture (designed, deferred for cost)
- Issue #294: Consider migrating from Ingress to Gateway API

**Recently Closed** (2026-01 / 2025-12):
- ~~Issue #148~~: metrics-server implemented as EKS addon
- ~~Issue #191~~: DORA metrics dashboard implemented
- ~~Issue #295~~: TLS/HTTPS implemented with cert-manager
- ~~Issue #302~~: TLS rate-limiting resolved with custom domain
- ~~Issue #303~~: Self-hosted runners evaluated

---

**Document Maintained By**: Platform Engineering Team
**Last Updated**: 2026-01-03
**Review Frequency**: Monthly during platform meetings
**Next EKS Version Check**: February 2026 (K8s 1.32 extended support begins ~March 2026)
