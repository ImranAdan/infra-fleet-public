# GitHub Environments Setup

This document explains how to configure GitHub Environments for deployment tracking and protection rules.

## Overview

GitHub Environments provide:
- **Deployment tracking** - View deployment history in the GitHub UI
- **Protection rules** - Require approvals before deploying to sensitive environments
- **Environment-scoped secrets** - Secrets only available to specific environments
- **Deployment URLs** - Direct links to deployed applications

## Current Configuration

| Workflow | Environment Source | Notes |
|----------|-------------------|-------|
| `infra-apply.yml` | `vars.ENVIRONMENT` or `staging` | Automatic on push to main |
| `rebuild-stack.yml` | `inputs.environment` | Manual dispatch with environment selection |
| `load-harness-ci.yml` | `vars.ENVIRONMENT` or `staging` | Automatic on version tags |

## Setup Instructions

### Step 1: Create the Environment

1. Go to your repository: **Settings > Environments**
2. Click **New environment**
3. Enter the environment name (e.g., `staging`, `production`)
4. Click **Configure environment**

### Step 2: Configure Protection Rules (Optional)

For production environments, consider adding:

| Rule | Staging | Production |
|------|---------|------------|
| Required reviewers | No | Yes (1+) |
| Wait timer | No | Optional (e.g., 5 min) |
| Deployment branches | `main` only | `main` only |

**To configure:**
1. In the environment settings, check **Required reviewers**
2. Add one or more reviewers who must approve deployments
3. Under **Deployment branches**, select **Selected branches** and add `main`

### Step 3: Set Repository Variable (Optional)

To change the default environment from `staging`:

1. Go to **Settings > Secrets and variables > Actions**
2. Click the **Variables** tab
3. Click **New repository variable**
4. Name: `ENVIRONMENT`
5. Value: Your environment name (e.g., `staging`)

### Step 4: Move Secrets to Environment (Optional)

For environment-specific secrets:

1. In the environment settings, scroll to **Environment secrets**
2. Click **Add secret**
3. Add secrets that should only be available to this environment

**Candidates for environment-scoped secrets:**
- `AWS_GITHUB_ACTIONS_ROLE_ARN` (if different per environment)
- `GRAFANA_ADMIN_PASSWORD`

## Viewing Deployments

After configuration, deployments appear in:

1. **Repository home page** - Right sidebar shows active deployments
2. **Deployments page** - `https://github.com/<owner>/<repo>/deployments`
3. **Pull request** - Shows deployment status for related changes
4. **Actions run** - Shows environment badge on jobs

## Multi-Environment Strategy

### Current State: Single Environment (Staging)

```
┌─────────────────────────────────────────────────────────────────┐
│                         staging                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐   │
│  │ EKS Cluster │   │     ECR     │   │   Flux GitOps       │   │
│  │  (staging)  │   │ (shared)    │   │ (k8s/applications)│  │
│  └─────────────┘   └─────────────┘   └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Future State: Multi-Environment

```
┌─────────────────────────────────────────────────────────────────┐
│                         staging                                  │
│  • Auto-deploy on main branch push                              │
│  • No approval required                                          │
│  • Nightly destroy (cost optimization)                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Promotion (manual approval)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        production                                │
│  • Required reviewers (1+)                                       │
│  • Deployment branches: main only                               │
│  • No auto-destroy                                               │
│  • Environment-specific secrets                                  │
└─────────────────────────────────────────────────────────────────┘
```

**To enable production:**
1. Create `production` environment in GitHub UI
2. Add required reviewers
3. Create production infrastructure in `infrastructure/production/`
4. Add production overlays in `k8s/` (Kustomize overlays)
5. Update workflows to deploy to production after staging succeeds

## Workflow Details

### infra-apply.yml

```yaml
environment:
  name: ${{ vars.ENVIRONMENT || 'staging' }}
```

- Triggers on push to `main` with infrastructure changes
- Uses repository variable `ENVIRONMENT` or defaults to `staging`
- Deploys Terraform infrastructure

### rebuild-stack.yml

```yaml
inputs:
  environment:
    type: choice
    options:
      - staging
      - production

environment:
  name: ${{ inputs.environment }}
```

- Manual workflow dispatch
- Dropdown to select target environment
- Full stack rebuild (Terraform + Flux bootstrap)

### load-harness-ci.yml

```yaml
environment:
  name: ${{ vars.ENVIRONMENT || 'staging' }}
```

- Triggers on version tags (`v*`)
- Pushes container image to ECR
- Flux Image Automation handles cluster deployment

## Troubleshooting

### Deployment not appearing in GitHub UI

1. Verify the environment exists in **Settings > Environments**
2. Check the workflow run logs for environment errors
3. Ensure the `environment:` block is correctly formatted

### "Environment not found" error

The environment name in the workflow must exactly match the name in GitHub UI (case-sensitive).

### Protection rules blocking deployment

If a deployment is waiting for approval:
1. Go to the workflow run in **Actions**
2. Click **Review deployments**
3. Select the environment and approve

## Related Documentation

| Document | Description |
|----------|-------------|
| [GITHUB-OIDC-SETUP.md](GITHUB-OIDC-SETUP.md) | AWS authentication setup |
| [MULTI-ENVIRONMENT-DESIGN.md](MULTI-ENVIRONMENT-DESIGN.md) | Future multi-environment architecture |
| [RELEASE-ENGINEERING-ROADMAP.md](RELEASE-ENGINEERING-ROADMAP.md) | Release engineering phases |
