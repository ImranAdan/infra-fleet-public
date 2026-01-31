# Terraform Cloud Setup Guide

This guide walks through configuring Terraform Cloud for remote state management and execution.

## Why Terraform Cloud?

**Problems it solves**:
- ✅ No local state files (state stored remotely)
- ✅ State persistence across GitHub Actions runs
- ✅ Built-in state locking (no DynamoDB needed)
- ✅ Run history and audit logs
- ✅ Remote execution (optional - faster, no GitHub Actions minutes consumed)
- ✅ Free tier sufficient for this project

**Without Terraform Cloud**: Each GitHub Actions run starts fresh, doesn't know what resources exist, tries to recreate everything → errors.

**With Terraform Cloud**: State persists, Terraform knows what exists, properly manages infrastructure lifecycle.

## Setup Steps

### 1. Create Terraform Cloud Workspace

1. Log into [Terraform Cloud](https://app.terraform.io)
2. Navigate to your organization: `your-terraform-org`
3. Click **"New Workspace"**
4. Choose workflow type:
   - **Option A (Recommended)**: **CLI-driven workflow** (we trigger from GitHub Actions)
   - **Option B**: VCS-driven workflow (Terraform Cloud monitors repo)
5. Configure workspace:
   - **Workspace Name**: `infra-fleet-staging` (for `clusters/staging`) and `infra-fleet-permanent` (for `infrastructure/permanent`)
   - **Project**: Default or create new
   - **Description**: e.g., "EKS staging cluster - destroyed nightly" / "Permanent shared infra (OIDC, ECR)"

### 2. Configure Workspace Settings

After creating the workspace:

#### Execution Mode
- **Settings → General**
- **Execution Mode**: Choose based on preference:
  - **Remote**: Runs execute on Terraform Cloud (recommended - faster, no GitHub minutes)
  - **Local**: Runs execute on GitHub Actions (uses your GitHub minutes)

#### Working Directory (if using VCS)
- **Settings → General**
- **Terraform Working Directory**: `clusters/staging`

#### Environment Variables - OIDC Authentication (Recommended)

We're using OIDC for secure, credential-less authentication to AWS!

**Settings → Variables → Add Variable**:

| Variable | Value | Category | Sensitive | Description |
|----------|-------|----------|-----------|-------------|
| `TFC_AWS_PROVIDER_AUTH` | `true` | Environment | No | Enable AWS OIDC authentication |
| `TFC_AWS_RUN_ROLE_ARN` | `arn:aws:iam::123456789012:role/GitHubActions-InfraFleet` | Environment | No | IAM role to assume (applies to both staging and permanent) |
| `AWS_REGION` | `eu-west-2` | Environment | No | Default AWS region |

**How it works**:
- ✅ No AWS access keys needed (more secure!)
- ✅ Terraform Cloud authenticates using OIDC tokens
- ✅ Same IAM role used by GitHub Actions
- ✅ Temporary credentials only (auto-expiring)
- ✅ Full audit trail in CloudTrail

**Alternative (Not recommended)**: Use AWS access keys as environment variables if OIDC doesn't work.

### 3. Generate Terraform Cloud API Token

GitHub Actions needs to authenticate to Terraform Cloud:

1. Go to **User Settings → Tokens** (top-right menu)
2. Click **"Create an API token"**
3. **Description**: `GitHub Actions - infra-fleet`
4. **Expiration**: Choose based on security preference (90 days or no expiration)
5. **Copy the token** (you won't see it again!)

### 4. Add Token to GitHub Secrets

Add the API token to GitHub repository secrets:

```bash
# Using gh CLI
gh secret set TF_API_TOKEN --body "your-terraform-cloud-token-here"

# Or manually via GitHub UI:
# 1. Go to: https://github.com/your-org/infra-fleet/settings/secrets/actions
# 2. Click "New repository secret"
# 3. Name: TF_API_TOKEN
# 4. Value: <paste token>
# 5. Click "Add secret"
```

### 5. Update GitHub Actions Workflows

The workflows already reference `TF_API_TOKEN`, but ensure the Terraform Cloud authentication is configured:

In `.github/workflows/rebuild-stack.yml` and `.github/workflows/nightly-destroy.yml`:

```yaml
- name: Setup Terraform
  uses: hashicorp/setup-terraform@v3
  with:
    terraform_version: 1.6.0
    cli_config_credentials_token: ${{ secrets.TF_API_TOKEN }}  # ← This authenticates to TF Cloud
```

(Already present in current workflows)

### 6. Initialize Terraform with Cloud Backend (per stack)

First time setup - migrate to Terraform Cloud (run separately per directory):

```bash
cd clusters/staging   # or infrastructure/permanent
terraform init -migrate-state   # include -migrate-state only if you have existing local state

# Terraform will detect the cloud backend and ask to migrate
# Answer "yes" to migrate local state (if any) to the correct workspace
```

If you have orphaned resources to clean up first, you can start fresh:
```bash
# Clean up orphaned resources first
aws iam delete-role --role-name session-manager-role  # (after removing policies)
aws logs delete-log-group --log-group-name /aws/eks/staging/cluster --region eu-west-2
# ... etc

# Then init fresh
cd clusters/staging
terraform init
```

## Execution Modes Comparison

### Remote Execution (Recommended)

**How it works**:
1. GitHub Actions triggers Terraform Cloud via API
2. Terraform Cloud downloads code from repo
3. Execution happens on Terraform Cloud infrastructure
4. Logs stream back to GitHub Actions

**Pros**:
- ✅ Faster (dedicated Terraform Cloud infrastructure)
- ✅ No GitHub Actions minutes consumed for terraform execution
- ✅ Better visibility in Terraform Cloud UI
- ✅ Consistent execution environment

**Cons**:
- ⚠️ Requires network access to AWS from Terraform Cloud IPs
- ⚠️ Slightly more complex setup

### Local Execution

**How it works**:
1. GitHub Actions runner executes terraform commands
2. State is stored/retrieved from Terraform Cloud
3. All execution on GitHub Actions runner

**Pros**:
- ✅ Simpler mental model
- ✅ Execution logs in GitHub Actions (familiar)

**Cons**:
- ❌ Consumes GitHub Actions minutes
- ❌ Slower (GitHub Actions runners vs Terraform Cloud)

## Workflow Updates Needed

The workflows need minor updates to work with Terraform Cloud:

### For Remote Execution

```yaml
- name: 🏗️ Terraform Infrastructure Build (Staging Only)
  run: |
    cd clusters/staging

    # Terraform Cloud handles init automatically
    # Just trigger the run via CLI
    terraform init
    terraform plan
    terraform apply -auto-approve
```

### For Local Execution

No changes needed - existing workflow commands work as-is.

## Testing the Setup

After configuration:

1. **Trigger rebuild workflow**: `gh workflow run rebuild-stack.yml`
2. **Monitor in Terraform Cloud**:
   - Go to workspace: https://app.terraform.io/app/your-terraform-org/workspaces/infra-fleet-staging
   - Watch run progress in real-time
   - Review state after completion
3. **Verify idempotency**: Run again - should show "No changes" (not errors!)

## Troubleshooting

### "Error: No valid credential sources found"

**Cause**: AWS credentials not configured in Terraform Cloud workspace

**Fix**: Add `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` to workspace environment variables

### "Error: Required token could not be found"

**Cause**: `TF_API_TOKEN` not set in GitHub secrets

**Fix**: Add token to GitHub repository secrets

### "Error: workspace not found"

**Cause**: Workspace name in `main.tf` doesn't match Terraform Cloud

**Fix**: Ensure workspace name matches exactly: `infra-fleet-staging`

### State Lock Errors

**Cause**: Previous run didn't complete (rare with Terraform Cloud)

**Fix**: Manually unlock in Terraform Cloud UI: Settings → Locks → Force Unlock

## OIDC Configuration (Already Done!)

The AWS infrastructure is already configured to trust Terraform Cloud via OIDC:

**What was configured** (in `infrastructure/permanent/github-oidc.tf`):

1. **Terraform Cloud OIDC Provider**:
   - Provider URL: `https://app.terraform.io`
   - Client ID: `aws.workload.identity`
   - Thumbprint: `9e99a48a9960b14926bb7f3b02e22da2b0ab7280`

2. **IAM Role Trust Policy Updated**:
   - Role: `GitHubActions-InfraFleet`
   - Now trusts BOTH:
     - GitHub Actions (`token.actions.githubusercontent.com`)
     - Terraform Cloud (`app.terraform.io`)
   - Scoped to specific organization and workspace

**Trust policy allows**:
- Organization: `your-terraform-org`
- Workspace: `infra-fleet-staging`
- All run phases (plan, apply, etc.)

**You just need to**:
1. Set environment variables in Terraform Cloud workspace (see above)
2. Terraform Cloud will automatically assume the IAM role using OIDC

## Cost Implications

**Terraform Cloud**:
- Free tier: Up to 500 resources (we're well under)
- Remote execution: Included in free tier
- State storage: Included

**AWS Authentication**:
- ✅ **OIDC (configured)**: No additional costs, more secure
- ❌ Access keys: Not needed, less secure

## Benefits Realized

After setup:
- ✅ **No more "already exists" errors** - Terraform knows what's deployed
- ✅ **True idempotency** - Can run workflows multiple times safely
- ✅ **Better debugging** - Full run history in Terraform Cloud UI
- ✅ **Collaboration ready** - Team members can see infrastructure state
- ✅ **Cost tracking** - Terraform Cloud shows resource counts and estimated costs

## Next Steps

After Terraform Cloud is configured:

1. Clean up orphaned resources from failed runs
2. Run rebuild workflow - should complete successfully
3. Verify cluster is deployed
4. Test nightly destruction
5. Test rebuild-after-destruction (state persists!)

---

**Last Updated**: 2025-11-19
**Status**: Setup guide for Terraform Cloud integration
**Required**: Resolves state management issues in automation workflows
