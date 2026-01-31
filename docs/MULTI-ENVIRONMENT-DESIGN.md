# Multi-Environment Promotion Strategy Design

> **Status: WIP** - Initial design captured, needs further refinement before implementation.

**Last Updated**: 2025-12-25

---

## Overview

This document outlines the design for a staging → production promotion strategy for infra-fleet. Implementation is deferred due to cost considerations (~$120/month minimum for production EKS).

**Design Choices:**
- **Infrastructure**: Terragrunt for DRY multi-environment management
- **GitOps**: Kustomize base/overlays pattern
- **Image Strategy**: Same image tag, manifest-only promotion

---

## Current State

### What Exists Today

| Component | Current State | Environment-Aware? |
|-----------|--------------|-------------------|
| **Terraform** | `infrastructure/staging/` and `infrastructure/permanent/` | Partially (permanent is shared) |
| **GitOps** | Flat structure in `k8s/applications/` | No - hardcoded "staging" |
| **CI/CD** | Single workflow per resource type | No - assumes staging |
| **GitHub Environments** | Not configured | N/A |
| **ECR** | Single repository `load-harness` | No |
| **IAM/OIDC** | Single role `GitHubActions-InfraFleet` | No |

### Key Hardcoded Values

- EKS cluster name: `"staging"` (eks.tf)
- VPC CIDR: `10.0.0.0/16` (vpc.tf)
- Region: `eu-west-2` (throughout)
- Ingress ALB group: `infra-fleet-staging` (ingress.yaml)
- ENVIRONMENT env var: `"staging"` (deployment.yaml)
- Terraform Cloud workspace: `infra-fleet-staging` (main.tf)

---

## Proposed Design

### 1. Infrastructure: Terragrunt

Terragrunt wraps Terraform to enable DRY multi-environment configurations.

**Proposed Structure:**
```
infrastructure/
├── terragrunt.hcl              # Root config (remote state, providers)
├── modules/                    # Reusable Terraform modules
│   ├── vpc/
│   ├── eks/
│   └── monitoring/
├── environments/
│   ├── staging/
│   │   └── terragrunt.hcl      # staging-specific vars
│   ├── production/
│   │   └── terragrunt.hcl      # production-specific vars
│   └── common.hcl              # Shared variables
└── permanent/                  # Unchanged (shared ECR, OIDC)
```

**Key Benefits:**
- Single source of truth for module code
- Environment configs are just variable overrides
- Built-in dependency management between stacks
- `terragrunt run-all` for multi-stack operations

**Example `environments/staging/terragrunt.hcl`:**
```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../modules//eks"
}

inputs = {
  environment     = "staging"
  cluster_name    = "staging"
  vpc_cidr        = "10.0.0.0/16"
  node_min_size   = 2
  node_max_size   = 4
  enable_nightly_destroy = true
}
```

**Example `environments/production/terragrunt.hcl`:**
```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../modules//eks"
}

inputs = {
  environment     = "production"
  cluster_name    = "production"
  vpc_cidr        = "10.1.0.0/16"
  node_min_size   = 3
  node_max_size   = 10
  enable_nightly_destroy = false
}
```

### 2. GitOps: Kustomize Base/Overlays

**Proposed Structure:**
```
k8s/
├── base/
│   └── applications/
│       └── load-harness/
│           ├── deployment.yaml    # No env-specific values
│           ├── service.yaml
│           ├── ingress.yaml
│           └── kustomization.yaml
└── overlays/
    ├── staging/
    │   ├── kustomization.yaml
    │   └── patches/
    │       └── deployment-patch.yaml
    └── production/
        ├── kustomization.yaml
        └── patches/
            └── deployment-patch.yaml
```

**Example `base/applications/load-harness/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: load-harness
spec:
  replicas: 1  # Overridden per environment
  template:
    spec:
      containers:
        - name: load-harness
          image: ECR_PLACEHOLDER:TAG_PLACEHOLDER
          env:
            - name: ENVIRONMENT
              value: PLACEHOLDER
```

**Example `overlays/staging/kustomization.yaml`:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base/applications/load-harness

namespace: staging

patches:
  - path: patches/deployment-patch.yaml

images:
  - name: ECR_PLACEHOLDER
    newName: 123456789.dkr.ecr.eu-west-2.amazonaws.com/load-harness
```

**Example `overlays/staging/patches/deployment-patch.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: load-harness
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: load-harness
          env:
            - name: ENVIRONMENT
              value: staging
          resources:
            limits:
              memory: 256Mi
            requests:
              memory: 128Mi
```

**Example `overlays/production/patches/deployment-patch.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: load-harness
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: load-harness
          env:
            - name: ENVIRONMENT
              value: production
          resources:
            limits:
              memory: 512Mi
            requests:
              memory: 256Mi
```

### 3. Image Promotion: Same Tag Strategy

**Flow:**
1. PR merged → Build image with tag `v1.2.3`
2. Push to single ECR repository
3. Update staging overlay: `newTag: v1.2.3`
4. Flux syncs to staging cluster
5. After validation, update production overlay: `newTag: v1.2.3`
6. Flux syncs to production cluster

**Benefits:**
- Exact same binary in both environments
- No rebuild or re-tag required
- Promotion is a Git commit (auditable)
- Rollback = revert the tag in overlay

### 4. GitHub Environments & CI/CD

**GitHub Environments:**

| Environment | Approval | Protection Rules |
|-------------|----------|------------------|
| `staging` | None | Auto-deploy on tag |
| `production` | Required (1+ reviewer) | Deployment branches: `main` only |

**Environment-Specific Secrets:**
```
staging:
  - AWS_GITHUB_ACTIONS_ROLE_ARN_STAGING
  - TF_API_TOKEN (same workspace org)

production:
  - AWS_GITHUB_ACTIONS_ROLE_ARN_PRODUCTION
  - TF_API_TOKEN (same workspace org)
```

**Workflow Changes:**

`infra-apply.yml` becomes environment-aware:
```yaml
jobs:
  apply-staging:
    environment: staging
    if: contains(github.ref, 'staging') || needs.detect.outputs.staging == 'true'
    # ...

  apply-production:
    environment: production
    needs: apply-staging  # Sequential deployment
    if: needs.detect.outputs.production == 'true'
    # ...
```

**Release Deployment Workflow:**
```yaml
name: Deploy Release

on:
  release:
    types: [published]

jobs:
  deploy-staging:
    environment: staging
    steps:
      - name: Update staging overlay
        run: |
          cd k8s/overlays/staging
          kustomize edit set image ECR_PLACEHOLDER=...:${{ github.event.release.tag_name }}
      - name: Commit and push
        run: git commit -am "deploy: staging ${{ github.event.release.tag_name }}"

  deploy-production:
    needs: deploy-staging
    environment: production  # Requires approval
    steps:
      - name: Update production overlay
        run: |
          cd k8s/overlays/production
          kustomize edit set image ECR_PLACEHOLDER=...:${{ github.event.release.tag_name }}
      - name: Commit and push
        run: git commit -am "deploy: production ${{ github.event.release.tag_name }}"
```

---

## Migration Path

### Phase 1: GitOps Restructure (Low Risk, No Cost)
1. Create `base/` and `overlays/staging/` structure
2. Move existing manifests to base
3. Create staging patches
4. Update Flux to point to overlay
5. Validate staging still works

### Phase 2: Terragrunt Migration (Medium Risk, No Cost)
1. Install Terragrunt in CI
2. Create `modules/` from existing staging code
3. Create `environments/staging/` terragrunt.hcl
4. Test with `terragrunt plan`
5. Migrate state (if needed)
6. Update CI workflows for terragrunt

### Phase 3: Production Environment (When Budget Allows)
1. Create `environments/production/` terragrunt.hcl
2. Create `overlays/production/` kustomize
3. Configure GitHub `production` environment
4. Create IAM role for production
5. Deploy production infrastructure
6. Configure Flux for production cluster

---

## Cost Summary

| Resource | Staging | Production | Total |
|----------|---------|------------|-------|
| EKS Control Plane | $72/mo | $72/mo | $144/mo |
| NAT Gateway | $32/mo | $32/mo | $64/mo |
| ALB | $16/mo | $16/mo | $32/mo |
| EC2 Nodes (min) | ~$50/mo | ~$75/mo | ~$125/mo |
| **Total** | ~$170/mo | ~$195/mo | **~$365/mo** |

> **Note**: Staging uses nightly destroy, so actual staging cost is ~$0 most of the time. Production would run 24/7.

---

## Considerations

### Why Terragrunt?
- **DRY**: Write module code once, configure per environment
- **State isolation**: Each environment has its own state
- **Dependency management**: Built-in support for cross-stack dependencies
- **Consistency**: Same source, different inputs

### Why Kustomize Overlays?
- **Native to Kubernetes**: No additional tooling required
- **Flux integration**: Works seamlessly with existing Flux setup
- **Transparent**: Easy to see what differs between environments
- **Patch-based**: Only specify differences, not full resources

### Why Same Image Tag?
- **Immutable artifacts**: What you test is what you deploy
- **Audit trail**: Git history shows exactly what was promoted
- **Simple rollback**: Just update the tag reference
- **No rebuild risk**: Same binary, same behavior

---

## Open Questions (To Refine)

1. **Terragrunt learning curve**: Is the team comfortable with Terragrunt?
2. **State migration**: How to migrate existing staging state to Terragrunt?
3. **Flux multi-cluster**: Single Flux instance or per-cluster?
4. **Database strategy**: How to handle database migrations across environments?
5. **Secrets management**: Sealed Secrets vs External Secrets Operator?

---

## Related Documentation

- [RELEASE-ENGINEERING-ROADMAP.md](RELEASE-ENGINEERING-ROADMAP.md) - Phase 4: Multi-Environment Promotion
- [GITOPS-SETUP.md](GITOPS-SETUP.md) - Current Flux configuration
- [Terragrunt Documentation](https://terragrunt.gruntwork.io/docs/)
- [Kustomize Documentation](https://kustomize.io/)
