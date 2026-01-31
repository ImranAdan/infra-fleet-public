# Design Decision Record (DDR)
## Terraform Cloud Access to Private EKS Cluster & Flux Bootstrap Issue

**Date:** 2025-02-21 (Updated: 2025-12-26)
**Author:** Imran Adan
**Status:** Approved
**Decision Type:** Architecture / Networking / CI/CD Execution Model

---

## Current State

**What's deployed today:**

| Component | Configuration |
|-----------|---------------|
| EKS Public Endpoint | `endpoint_public_access_cidrs = ["0.0.0.0/0"]` (open to all) |
| Authentication | IAM-based (`authentication_mode = "API_AND_CONFIG_MAP"`) |
| Flux Bootstrap | GitHub Actions workflow (not Terraform) |
| Stack Lifecycle | Ephemeral (~8-10 hours/day, nightly destroy at 8 PM UTC) |

**Security controls:**
- No anonymous access (IAM authentication required)
- Trivy findings AVD-AWS-0040/AVD-AWS-0041 documented in `.trivyignore`

---

## Historical Investigation

> **Note:** This section documents the original problem that led to this decision. It does not reflect the current configuration.

### Original Setup (February 2025)

We attempted to deploy EKS with restricted public access:

- Public API endpoint enabled
- Restricted access via `publicAccessCidrs`
- Terraform Cloud IP ranges whitelisted (14 published IPs)
- Developer local IPs whitelisted

### The Problem

Despite whitelisting TFC IPs, Terraform Cloud runs failed when applying Flux bootstrap:

```
Error: Bootstrap run error
CRD dry-run failed: i/o timeout
dial tcp <EKS API PUBLIC IP>:443: i/o timeout
```

Local `kubectl` worked. Cluster was healthy.

This blocked:

- `flux_bootstrap_git`
- Any resource using the Kubernetes provider
- Any Terraform provider requiring direct API communication with EKS

### Root Cause Analysis

**The 14 Terraform Cloud IPs are correct** — these IPs (notifications, VCS, sentinel) match the `/meta/ip-ranges` API output.

**BUT — Terraform Cloud execution does not use those IPs.** HashiCorp states:

- Published IPs cover TFC API, notifications, VCS, sentinel
- Not the IPs of Terraform execution workers
- Worker IPs are dynamic, ephemeral, and not published
- They cannot be reliably allow-listed
- Recommended solution: use Terraform Cloud Agents

**Result with restricted CIDRs:**
- EKS endpoint only allowed developer IPs + 14 static TFC IPs
- TFC workers connected from unpredictable AWS IPs
- Packets were dropped → `i/o timeout` → Flux bootstrap failed

### Verification

Opening the endpoint to `0.0.0.0/0` confirmed the issue:
- Terraform Cloud apply succeeded immediately
- This proved it was an IP allow-listing issue, not a cluster problem

---

## Decision

We will not attempt to maintain CIDR allow-lists for TFC worker IPs.

---

## Option A — Use Terraform Cloud Agents (Recommended)

Deploy the Terraform Cloud Agent inside:

- Same VPC as EKS  
- Peered network  
- Private link  

This ensures:

- All Terraform apply traffic comes from known, fixed IPs  
- Kubernetes provider works reliably  
- Flux bootstrap works  
- EKS endpoint can be restricted with minimal exposure  

**Pros**  
- Strongest security  
- Predictable network  
- Works with private-only EKS endpoints  

**Cons**  
- Additional infrastructure  
- More setup complexity  

---

## Option B — Relax EKS Public CIDRs (Fallback)

Set:

```hcl
publicAccessCidrs = ["0.0.0.0/0"]
```

**Pros**  
- Fast fix  
- No new infra  

**Cons**  
- Wider EKS API exposure  

---

## Option C — Run Flux Bootstrap Outside Terraform Cloud ✅ IMPLEMENTED

**Status**: Implemented (December 2024)

Flux is bootstrapped via GitHub Actions workflow (`.github/workflows/rebuild-stack.yml`):

```bash
flux bootstrap github \
  --owner=your-org \
  --repository=infra-fleet \
  --path=k8s/flux-system \
  --components=source-controller,kustomize-controller,helm-controller \
  --components-extra=image-reflector-controller,image-automation-controller \
  --version=v2.7.3 \
  --token-auth
```

**Pros**
- Keeps strict network boundary for Flux operations
- Eliminates provider initialization issues when cluster is down
- PR plans/applies work regardless of cluster state
- Aligns with Flux's GitOps philosophy (Flux manages itself via Git)

**Cons**
- Split workflow (Terraform for AWS, GitHub Actions for Flux)
- Accepted trade-off: well-documented in [GITOPS-SETUP.md](GITOPS-SETUP.md)  

---

## Decision Summary

**Chosen: Option B + Option C (Hybrid Approach)**

For this ephemeral dev/staging stack, we implemented a hybrid approach:

### Option B — Open CIDR (0.0.0.0/0)
Required for Terraform Cloud workers to run `terraform plan/apply` on AWS resources:
1. EKS public endpoint open to 0.0.0.0/0
2. IAM authentication required (no anonymous access)
3. Stack runs ~8-10 hours/day (nightly destroy at 8 PM UTC)

### Option C — Flux Bootstrap via GitHub Actions ✅ IMPLEMENTED
Flux is now bootstrapped outside Terraform via `.github/workflows/rebuild-stack.yml`:
1. Eliminates Kubernetes/Flux provider initialization issues
2. PR plans work regardless of cluster state
3. Decouples Terraform (AWS) from Kubernetes lifecycles

See [GITOPS-SETUP.md](GITOPS-SETUP.md) for detailed explanation.

**Why not TFC Agents (Option A)?**
- Additional infrastructure cost (~$15-30/month)
- Operational complexity (EC2/ECS, networking, maintenance)
- Overkill for ephemeral non-production workloads

**Risk Acceptance:**
- Trivy findings AVD-AWS-0040 and AVD-AWS-0041 are documented and ignored
- See: `infrastructure/staging/.trivyignore`

**Future consideration:**
For production or persistent environments, consider:
- TFC Agents for tighter network controls on Terraform operations
- Restricting EKS public access CIDRs (if TFC Agents deployed)
- Private-only EKS endpoint with VPN/bastion access

Note: Option C (GitHub Actions-based Flux bootstrap) is already implemented and working.

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [GITOPS-SETUP.md](GITOPS-SETUP.md) | Why Flux is outside Terraform (detailed explanation) |
| [EKS-ACCESS.md](EKS-ACCESS.md) | EKS access patterns and security trade-offs |
| [TERRAFORM-CLOUD-SETUP.md](TERRAFORM-CLOUD-SETUP.md) | Terraform Cloud configuration |

---

## Changelog

- **2025-12-26**: Restructured document - added Current State section, clarified historical vs current configuration
- **2025-12-26**: Updated to reflect Option C implementation (Flux via GitHub Actions)
- **2025-12-06**: Previous update
- **2025-02-21**: Initial DDR created
