# GitOps Setup Guide - Flux v2

**Status**: Deployed and operational (5 controllers)
**Last Updated**: 2025-12-24

This guide documents the GitOps setup for the infra-fleet platform using Flux v2, including the architectural decisions behind the design.

## Overview

Flux is bootstrapped via the `rebuild-stack.yml` GitHub Actions workflow using the `flux bootstrap github` CLI command. This is a deliberate architectural choice that decouples GitOps deployment from infrastructure provisioning.

| Component | Managed By |
|-----------|------------|
| VPC, Subnets, NAT Gateway | Terraform |
| EKS Cluster, Node Groups | Terraform |
| IAM Roles (IRSA) | Terraform |
| EKS Addons (CoreDNS, VPC CNI, etc.) | Terraform |
| Flux Controllers | CLI (`flux bootstrap github`) |
| Application Workloads | Flux GitOps |

**Key characteristics:**
- **5 controllers**: source-controller, kustomize-controller, helm-controller, image-reflector-controller, image-automation-controller
- **Automated image updates**: Flux Image Automation scans ECR and updates manifests automatically
- **Single repository**: No separate gitops repo - manifests live in `k8s/`
- **Auto-syncs**: Reconciles every 1 minute from the `main` branch

## Why Flux is Outside Terraform

### The Problem

When Flux was managed by Terraform via the `flux_bootstrap_git` resource, the staging cluster's ephemeral nature created a fundamental conflict:

1. **Provider Initialization Issue**: The Flux and Kubernetes Terraform providers require a live EKS cluster to initialize. Terraform initializes ALL providers BEFORE evaluating any resources or conditionals.

2. **Nightly Destroy Impact**: After the nightly destroy job runs at 8 PM UTC, the cluster is down. However, if Flux was in Terraform state, any subsequent `terraform plan` or `apply` would fail:

   ```
   Error: Kubernetes Client
   cannot load kubeconfig: invalid configuration: no configuration has been provided
   ```

3. **Normal Workflows Blocked**: This meant that:
   - PR plans couldn't run when the cluster was down
   - Merge applies to main would fail
   - All infrastructure changes were blocked until a rebuild

4. **Toggle Variables Don't Work**: A `manage_flux = false` variable doesn't help because provider initialization happens BEFORE resource evaluation. The Kubernetes provider still tries to connect.

### The Solution

Flux is now bootstrapped via the `flux bootstrap github` CLI command in the rebuild-stack workflow. This approach:

1. **Decouples Lifecycles**: Terraform manages AWS infrastructure only
2. **Eliminates Provider Issues**: No Kubernetes/Flux providers in Terraform
3. **Is Idempotent**: Safe to run on every rebuild (Flux's design philosophy)
4. **Is GitOps Native**: Flux's state lives in Git, not Terraform state

### Benefits

**For Daily Operations:**
- PR plans always work regardless of cluster state
- Merge applies always work
- No "cannot connect to cluster" provider errors

**For Architecture:**
- Clear separation between infrastructure and GitOps
- Matches Flux's philosophy of managing itself via Git
- Reduced Terraform state complexity (AWS-only)

## Workflow Dependencies

```
┌─────────────────────────────────────────────────────────────────┐
│                    PR to main branch                            │
│                          │                                      │
│                          ▼                                      │
│                 ┌─────────────────┐                             │
│                 │  infra-plan.yml │  ← Works regardless of      │
│                 │  terraform plan │    cluster state            │
│                 └─────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Merge to main                                │
│                          │                                      │
│                          ▼                                      │
│                 ┌──────────────────┐                            │
│                 │  infra-apply.yml │  ← Works regardless of     │
│                 │  terraform apply │    cluster state           │
│                 └──────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                Manual Trigger: Rebuild Stack                    │
│                          │                                      │
│          ┌───────────────┼───────────────┐                      │
│          ▼               ▼               ▼                      │
│  ┌──────────────┐ ┌─────────────┐ ┌─────────────────┐           │
│  │  Terraform   │ │  Configure  │ │  Bootstrap Flux │           │
│  │    Apply     │→│   kubectl   │→│  (CLI command)  │           │
│  └──────────────┘ └─────────────┘ └─────────────────┘           │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  Nightly: 8 PM UTC                              │
│                          │                                      │
│                          ▼                                      │
│              ┌────────────────────────┐                         │
│              │  nightly-destroy.yml   │                         │
│              │  - Cleanup K8s (ALBs)  │                         │
│              │  - terraform destroy   │                         │
│              └────────────────────────┘                         │
│                          │                                      │
│                          ▼                                      │
│              Cluster is destroyed, but                          │
│              infra-plan/apply still work                        │
└─────────────────────────────────────────────────────────────────┘
```

## Kubernetes Manifest Validation Pipeline

Before manifests are merged to `main`, the `k8s-manifest-validate` workflow runs a sequential validation pipeline:

```
┌─────────────────────────────────────────────────────────────────┐
│                    PR to main branch                            │
│                          │                                      │
│            ┌─────────────┴─────────────┐                        │
│            ▼                           ▼                        │
│    ┌──────────────┐            ┌──────────────┐                 │
│    │  YAML Syntax │            │   Other CI   │                 │
│    │  (yamllint)  │            │    Checks    │                 │
│    └──────┬───────┘            └──────────────┘                 │
│           │                                                     │
│           ▼                                                     │
│    ┌──────────────┐                                             │
│    │  K8s Schema  │  ← Validates against K8s API schemas        │
│    │ (kubeconform)│                                             │
│    └──────┬───────┘                                             │
│           │                                                     │
│           ▼                                                     │
│    ┌──────────────┐                                             │
│    │   Kyverno    │  ← Enforces organizational policies         │
│    │   Policies   │    (block-default-namespace, etc.)          │
│    └──────────────┘                                             │
└─────────────────────────────────────────────────────────────────┘
```

**Fail-fast behavior**: If YAML syntax fails, schema validation doesn't run. If schema fails, policy validation doesn't run.

See [policies/README.md](../policies/README.md) for policy details.

## Architecture

```
infra-fleet (Git Repository)
├── .github/workflows/
│   └── rebuild-stack.yml          # Bootstraps Flux via `flux bootstrap github`
├── infrastructure/staging/
│   └── flux.tf                    # Documentation only (Flux moved to workflow)
└── k8s/
    ├── flux-system/flux-system/   # Flux's own manifests (managed by Flux)
    │   ├── gotk-components.yaml   # Flux controllers
    │   ├── gotk-sync.yaml         # GitRepository + root Kustomization
    │   ├── kustomization.yaml     # Kustomize config
    │   └── kustomizations.yaml    # Child Kustomizations for infra/apps
    ├── infrastructure/
    │   ├── namespaces/            # Namespace definitions
    │   ├── helm-repositories/     # HelmRepository sources
    │   ├── aws-load-balancer-controller/  # ALB Controller HelmRelease
    │   ├── observability/         # Prometheus stack
    │   └── flux-image-automation/ # ImageRepository, ImagePolicy, ImageUpdateAutomation
    └── applications/
        └── load-harness/
            ├── deployment.yaml    # App deployment (image tag auto-updated by Flux)
            ├── service.yaml
            ├── ingress.yaml
            ├── hpa.yaml
            └── servicemonitor.yaml
```

## CRD Ordering: Infrastructure vs Applications

### The Problem

Flux **dry-runs ALL resources before applying ANY**. This creates a chicken-and-egg problem for Custom Resource Definitions (CRDs):

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FLUX DRY-RUN PHASE                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Flux reads all YAML files in infrastructure/ folder:                   │
│                                                                         │
│    1. pushgateway.yaml (Deployment + Service)     ──► dry-run ✅        │
│    2. kube-prometheus-stack HelmRelease           ──► dry-run ✅        │
│    3. pushgateway ServiceMonitor                  ──► dry-run ❌        │
│                                                                         │
│  ServiceMonitor fails because:                                          │
│  - It uses API: monitoring.coreos.com/v1                                │
│  - That CRD doesn't exist yet (installed BY kube-prometheus-stack)      │
│  - Flux can't validate a resource against a non-existent CRD            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

The error looks like:
```
ServiceMonitor/observability/pushgateway dry-run failed:
no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
```

### The Solution

Split CRD-dependent resources across Kustomizations:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: Infrastructure Kustomization                                   │
│  ──────────────────────────────────────                                  │
│                                                                          │
│  k8s/infrastructure/observability/pushgateway.yaml                       │
│    └── Deployment (pushgateway pod)                                      │
│    └── Service (ClusterIP on port 9091)                                  │
│                                                                          │
│  k8s/infrastructure/observability/kube-prometheus-stack/helmrelease.yaml │
│    └── Installs Prometheus Operator                                      │
│    └── Installs ServiceMonitor CRD  ◄─── CRD created here                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ dependsOn: infrastructure
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: Applications Kustomization                                     │
│  ────────────────────────────────────                                    │
│                                                                          │
│  k8s/applications/observability/pushgateway-monitor.yaml                 │
│    └── ServiceMonitor (tells Prometheus to scrape pushgateway)           │
│                                                                          │
│  By the time this runs, the CRD exists ✅                                │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Affected Resource Types

This pattern applies to any resource using a CRD installed by a HelmRelease:

| CRD Resource | Installed By | Place In |
|--------------|--------------|----------|
| `ServiceMonitor` | kube-prometheus-stack | `applications/` |
| `PodMonitor` | kube-prometheus-stack | `applications/` |
| `PrometheusRule` | kube-prometheus-stack | `applications/` |
| `Certificate` | cert-manager | `applications/` (or `cert-manager-issuer/`) |
| `ClusterIssuer` | cert-manager | `cert-manager-issuer/` (separate Kustomization) |
| `Canary` | flagger | `applications/` |
| `MetricTemplate` | flagger | `applications/` |

### Example: Adding a New ServiceMonitor

**Wrong** (will fail):
```
k8s/infrastructure/my-app/
├── deployment.yaml
├── service.yaml
└── servicemonitor.yaml  ❌ CRD doesn't exist during dry-run
```

**Correct**:
```
k8s/infrastructure/my-app/
├── deployment.yaml
└── service.yaml

k8s/applications/my-app/
└── servicemonitor.yaml  ✅ CRD exists because applications depends on infrastructure
```

### Dependency Chain

From `k8s/flux-system/flux-system/kustomizations.yaml`:

```yaml
# Infrastructure runs first (no dependencies)
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infrastructure
spec:
  path: ./k8s/infrastructure

---
# Applications waits for infrastructure to be healthy
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: applications
spec:
  path: ./k8s/applications
  dependsOn:
    - name: infrastructure  # ◄── Ensures CRDs exist before applying
```

## Image Update Flow

Flux Image Automation handles the complete CI/CD flow:

```
1. Developer pushes code to applications/load-harness/
2. GitHub Actions: Test → Build → Push to ECR (with semver tag like v1.2.3)
3. Flux image-reflector-controller scans ECR (every 1 minute)
4. Flux image-automation-controller detects new tag matching ImagePolicy
5. Flux commits updated image tag to k8s/applications/load-harness/deployment.yaml
6. Flux kustomize-controller applies the change to the cluster
```

**No CI manifest updates required** - Flux handles everything after ECR push.

The deployment manifest contains an image policy marker:
```yaml
image: 123456789012.dkr.ecr.eu-west-2.amazonaws.com/load-harness:v1.1.1 # {"$imagepolicy": "flux-system:load-harness"}
```

## Flux Controllers

| Controller | Purpose |
|------------|---------|
| source-controller | Monitors Git repository, fetches manifests |
| kustomize-controller | Applies Kustomizations to cluster |
| helm-controller | Manages HelmReleases |
| image-reflector-controller | Scans container registries for new tags |
| image-automation-controller | Commits image tag updates to Git |

## How Flux is Bootstrapped

### Rebuild Workflow Sequence

The `rebuild-stack.yml` workflow executes these steps:

```
1. Health Check
   └── Verify main branch has successful infra-apply run

2. Terraform Apply
   └── Create VPC, EKS, IAM roles, addons
   └── Export outputs (vpc_id, cluster_name, aws_account_id, ecr_registry)

3. Configure kubectl
   └── aws eks update-kubeconfig --name staging

4. Cluster Health Check
   └── Wait for nodes to be Ready
   └── Wait for CoreDNS pods to be Running

5. Create terraform-outputs ConfigMap
   └── kubectl create configmap terraform-outputs ...

6. Bootstrap Flux
   └── flux bootstrap github --owner=... --repository=...

7. Verify Flux
   └── Check Flux pods are running
   └── Verify GitRepository/Kustomization reconciliation
```

### Bootstrap Command

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

### terraform-outputs ConfigMap

Flux needs AWS infrastructure values for variable substitution in GitOps manifests. This ConfigMap is created via kubectl in the rebuild workflow:

```yaml
- name: Create terraform-outputs ConfigMap
  run: |
    kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -
    kubectl create configmap terraform-outputs \
      --namespace=flux-system \
      --from-literal=VPC_ID=${{ steps.terraform.outputs.vpc_id }} \
      --from-literal=CLUSTER_NAME=${{ steps.terraform.outputs.cluster_name }} \
      --from-literal=AWS_REGION=${{ env.AWS_REGION }} \
      --from-literal=AWS_ACCOUNT_ID=${{ steps.terraform.outputs.aws_account_id }} \
      --from-literal=ENVIRONMENT=staging \
      --from-literal=ECR_REGISTRY=${{ steps.terraform.outputs.ecr_registry }} \
      --dry-run=client -o yaml | kubectl apply -f -
```

**You do not need to bootstrap Flux manually** - the rebuild workflow handles this.

## Verification

### Check Flux Status

```bash
# Connect to cluster via Session Manager
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=session-manager-jumpbox" \
            "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --region eu-west-2)

aws ssm start-session --target $INSTANCE_ID --region eu-west-2

# Check Flux controllers (should see 5 pods)
kubectl get pods -n flux-system

# Check sync status
flux get all

# Check image automation
flux get images all
```

### Verification Checklist

- [ ] 5 Flux controllers running in `flux-system` namespace
- [ ] GitRepository `flux-system` shows "Fetched revision: main@sha1:xxxxx"
- [ ] Kustomizations show "Applied revision: main@sha1:xxxxx"
- [ ] ImageRepository shows latest ECR tags
- [ ] ImagePolicy shows selected tag
- [ ] Application pods running in `applications` namespace

## Testing GitOps Flow

### Manual Manifest Change

```bash
# Edit a manifest
vim k8s/applications/load-harness/deployment.yaml

# Commit and push
git add k8s/
git commit -m "chore: update load-harness config"
git push origin main

# Wait 1-2 minutes, then verify
kubectl get pods -n applications
```

### Trigger Image Update

```bash
# Create a new release tag (triggers CI)
git tag v1.2.0
git push origin v1.2.0

# CI builds and pushes to ECR
# Flux detects new tag and updates deployment.yaml automatically
# Check the commit history for Flux's automated commits
```

## Troubleshooting

### Flux Bootstrap Fails

1. **Check GitHub Token**: Ensure `FLUX_GITHUB_TOKEN` secret has repo permissions
2. **Check Network**: Cluster must have internet access for Flux to reach GitHub
3. **Check Version**: Flux CLI version should match `--version` parameter

### Flux pods not starting

```bash
kubectl logs -n flux-system deploy/source-controller
kubectl logs -n flux-system deploy/kustomize-controller
kubectl logs -n flux-system deploy/image-reflector-controller
```

### GitRepository not syncing

```bash
kubectl describe gitrepository flux-system -n flux-system
flux get sources git
```

### Image updates not working

```bash
# Check image scanning
flux get images repository
kubectl describe imagerepository load-harness -n flux-system

# Check image policy
flux get images policy
kubectl describe imagepolicy load-harness -n flux-system

# Check automation status
flux get images update
kubectl describe imageupdateautomation load-harness -n flux-system
```

### Kustomization failing

```bash
kubectl describe kustomization -n flux-system
flux get kustomizations

# Common issues:
# - Invalid YAML syntax
# - Missing namespace
# - Image pull errors (ECR permissions)
```

### ConfigMap Not Created

1. **Verify Namespace**: `flux-system` namespace must exist
2. **Check kubectl**: Ensure kubeconfig is properly configured
3. **Check Outputs**: Terraform outputs must be exported correctly

### Force reconciliation

```bash
flux reconcile source git flux-system
flux reconcile kustomization flux-system
flux reconcile image repository load-harness
```

## Useful Commands

```bash
# Check Flux version and status
flux version
flux check

# Get all Flux resources
flux get all

# Get image automation status
flux get images all

# Reconcile manually (force sync)
flux reconcile source git flux-system
flux reconcile kustomization flux-system

# Suspend/resume reconciliation
flux suspend kustomization applications
flux resume kustomization applications

# View Flux logs
flux logs --level=error
flux logs --kind=Kustomization --name=applications
```

## File Reference

| File | Purpose |
|------|---------|
| `.github/workflows/rebuild-stack.yml` | Bootstraps Flux on cluster rebuild |
| `infrastructure/staging/flux.tf` | Documentation only (explains Flux moved to workflow) |
| `infrastructure/staging/outputs-configmap.tf` | Terraform outputs for workflow |
| `k8s/flux-system/` | Flux's own manifests (managed by Flux) |
| `k8s/infrastructure/` | Platform resources (namespaces, Helm repos, controllers) |
| `k8s/infrastructure/flux-image-automation/` | Image scanning and update automation |
| `k8s/applications/` | Application deployments |

## Cost Impact

Flux configuration resource usage:
- **Controllers**: 5 pods (~150m CPU, ~300Mi memory total)
- **Storage**: Negligible (small Git cache)
- **Network**: Minimal (Git pull + ECR scan every 1 minute)

**Estimated impact:** < $1/month

## Security Notes

- Flux bootstrap uses GitHub Actions OIDC (no long-lived tokens)
- Deploy key has write access (required for image automation commits)
- SSH key generated during bootstrap (stored in cluster secrets)
- Flux runs with cluster-admin permissions
- Image pull uses EKS node IAM role (ECR permissions via IRSA)
- All image automation commits are signed by Flux

## Historical Context

Prior to December 2024, Flux was bootstrapped via Terraform using:

```hcl
# OLD APPROACH - No longer used
resource "flux_bootstrap_git" "this" {
  depends_on = [module.eks]
  path       = "k8s/flux-system"
}
```

This was removed because of the provider initialization issues described in [Why Flux is Outside Terraform](#why-flux-is-outside-terraform). The decision was made to move Flux outside Terraform entirely, aligning with Flux's GitOps philosophy where Flux manages its own state via Git.

---

**Questions?** Check the [official Flux docs](https://fluxcd.io/flux/) or open an issue.
