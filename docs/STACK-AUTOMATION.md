# Stack Automation Documentation

## Overview

This document describes the automated stack management system that destroys infrastructure nightly to optimize costs while preserving full context for seamless resumption.

## Cost Optimization

### Current Configuration (with ALB)
- **When Running (24/7)**: ~$88/month
  - EKS Cluster: $72/month
  - NAT Gateway (8hrs/day): $11.40/month
  - EC2 t3.small Spot (8hrs/day): $5/month
  - Application Load Balancer: ~$17/month

### With Nightly Automation
- **Estimated Monthly Cost**: ~$41/month (8 hours/day usage)
- **Savings**: ~$47/month (54% reduction)
- **Breakdown**: EKS control plane runs 24/7, compute/networking only during work hours

## Automation Workflows

### 1. Nightly Destruction (Automated + Manual)

**File**: `.github/workflows/nightly-destroy.yml`

**Version**: v3 Multi-Job Workflow (as of 2025-11-26)
**Schedule**: Every night at 8 PM UTC (hard stop for work day)
**Triggers**:
- Automatic (scheduled)
- Manual (workflow_dispatch via GitHub Actions UI or CLI)

**Workflow Structure** (5 separate jobs):
1. 📊 **Pre-Destroy Verification** - Check cluster state, run verification script
2. 🧹 **Cleanup Kubernetes Resources** - Hybrid cleanup approach (detailed below)
3. ✅ **Post-Cleanup Verification** - Verify no orphaned ALBs/ENIs
4. 🔥 **Terraform Destroy** - Only if cleanup succeeded (or force flag set)
5. 📋 **Final Report** - Idempotency check, create GitHub issue on failure

**Key Features**:
- **Visual Separation**: Each phase shows as separate box in GitHub UI
- **Fail-Fast**: Each job can fail independently
- **Conditional Execution**: Terraform destroy only runs if cleanup successful
- **Idempotency**: Can run multiple times safely
- **Error Reporting**: Auto-creates GitHub issue on scheduled run failures

**Process**:

#### Step 0: Suspend Flux GitOps
**Purpose**: Prevent Flux from recreating resources during cleanup (race condition)

The cleanup script automatically:
- Suspends the `applications` kustomization
- Waits 5 seconds for suspension to take effect
- Prevents Flux from recreating deleted resources

**Why this matters**: Flux reconciles every ~1 minute. Without suspension, Flux would detect
deleted resources and recreate them before Terraform destroy runs, causing orphaned ALBs (~$17/month each).

**Technical detail**: See Issue #30 for race condition documentation and long-term considerations.

#### Step 1: Kubernetes Resource Cleanup (Hybrid Approach)
**Purpose**: Prevent orphaned AWS resources (ALBs, ENIs, security groups, EBS volumes)

**Version**: v2 (Hybrid Cleanup) - as of 2025-11-26
**Script**: `scripts/cleanup-k8s-resources-v2.sh`

**Hybrid Strategy**:
- **Phase 1**: Kubernetes-native cleanup (if cluster healthy)
  - Suspend Flux to prevent resource recreation
  - Delete all Ingress resources → triggers ALB deletion via ALB controller
  - Delete LoadBalancer Services → triggers NLB/CLB deletion
  - Delete PersistentVolumeClaims → triggers EBS volume detachment
  - Wait for cloud provider to complete deletions (60-90s for ALBs)

- **Phase 2**: AWS tag-based cleanup (fallback when cluster destroyed/unhealthy)
  - Query AWS API for resources by tags:
    - ALBs: `elbv2.k8s.aws/cluster: staging`
    - ENIs: `kubernetes.io/cluster/staging: owned`
    - Security Groups: Same tags
  - Delete resources directly via AWS API
  - Retry logic for security groups (5 attempts, 15s delay)

- **Phase 3**: Verification
  - Check for remaining ALBs and ENIs
  - **Only fails if ALBs or ENIs remain** (these block VPC deletion)
  - Security Groups allowed to remain (managed by Terraform)

**Why this matters**: Kubernetes controllers create AWS resources not tracked by Terraform.
- ALB controller creates ALBs, Target Groups, Security Groups
- These resources have Elastic Network Interfaces (ENIs) with Elastic IPs
- ENIs with EIPs prevent Internet Gateway detachment, blocking VPC deletion
- Without cleanup: ~$17/month per orphaned ALB + potential destroy failures

**Technical Insight**:
```
Terraform → VPC, EKS, IAM
    ↓
Flux → Kubernetes manifests
    ↓
ALB Controller → ALBs, ENIs, Security Groups (NOT tracked!)
```

See `docs/implementation-summary-hybrid-cleanup.md` for complete technical details.

#### Step 2: Terraform Destruction
- Authenticate via GitHub Actions OIDC
- Run `terraform destroy -auto-approve` on `infrastructure/staging/`
- Destroys: EKS cluster, VPC, IAM roles, subnets, NAT gateway
- Preserves: Permanent infrastructure (OIDC provider, ECR, GitHub Actions IAM role)
- **Flux Git cleanup disabled**: `delete_git_manifests = false` prevents SSH authentication errors

**Note**: EKS control plane billing stops immediately (~$72/month saved)

**Known Issues Resolved**:
- ✅ Flux race condition (PR #31) - Suspension prevents resource recreation
- ✅ Flux SSH authentication error during destroy (PR #32) - Git cleanup disabled
- ✅ Orphaned ALBs/security groups (PR #29) - Cleanup script handles K8s resources

### 2. Manual Rebuild (On-Demand)

**File**: `.github/workflows/rebuild-stack.yml`

**Trigger**: Manual dispatch (green button in GitHub Actions)
**Prerequisite**: Main branch must be healthy (checks latest `infra-apply` run)

**Process**:

#### Step 1: Health Gate
- Query GitHub API for latest `infra-apply` workflow run on main
- Verify status is "completed" and conclusion is "success"
- Block rebuild if main branch is unhealthy
- Can be overridden with `force_rebuild` parameter

#### Step 2: Infrastructure Build
- Authenticate via GitHub Actions OIDC
- Validate Terraform configuration (`terraform validate`)
- Run `terraform init && terraform apply -auto-approve`
- Creates: EKS cluster, VPC, subnets, NAT gateway, IAM roles
- Duration: ~15-20 minutes for full stack creation

#### Step 3: Cluster Health Checks
**New approach** (no Session Manager needed):
- Configure kubectl directly from GitHub Actions (has EKS cluster admin access)
- Wait for nodes to be ready (max 5 minutes)
- Wait for CoreDNS to be ready (max 5 minutes)
- Display cluster state (nodes, system pods, Flux status)

#### Step 4: Status Report
- Display cluster name, region, access method
- Show estimated monthly cost (~$58 with ALB)
- Provide kubectl connection command
- Ready for work resumption

## Safety Measures

### Context Preservation
- **Complete State Capture**: All cluster and application state saved before destruction
- **Git Integration**: Context automatically committed and versioned
- **Restoration Ready**: Full context available for immediate work resumption

### Error Handling
- **Force Cleanup**: Handles stuck or orphaned resources
- **Lock Breaking**: Bypasses Terraform state locks if necessary
- **Graceful Failures**: Continues cleanup even if individual steps fail

### Health Checks
- **Pre-Rebuild Validation**: Only rebuilds if main branch is healthy
- **Post-Rebuild Verification**: Confirms all systems operational
- **Status Reporting**: Clear success/failure indicators

## Required Configuration

### AWS Authentication with OIDC

This project uses **OpenID Connect (OIDC)** for secure authentication to AWS - **no long-lived access keys required!**

**Setup Steps**:

1. **Deploy Permanent Infrastructure** (one-time setup):
   ```bash
   cd infrastructure/permanent
   terraform init
   terraform apply  # Creates OIDC provider and IAM role
   ```

   **This is permanent and never destroyed** - ensuring workflows always have authentication.

2. **Configure GitHub Secret** (just one secret needed):
   - Go to: GitHub repository → Settings → Secrets and variables → Actions
   - Add secret:
     - **Name**: `AWS_GITHUB_ACTIONS_ROLE_ARN`
     - **Value**: Copy from `terraform output github_actions_role_arn`

**That's it!** The workflows will automatically use OIDC to get temporary AWS credentials.

**Benefits**:
- ✅ No AWS access keys stored in GitHub
- ✅ Temporary credentials (auto-expire after 1 hour)
- ✅ No credential rotation needed
- ✅ Enhanced security with repository restrictions

**For detailed OIDC setup instructions**, see: [docs/GITHUB-OIDC-SETUP.md](GITHUB-OIDC-SETUP.md)

### IAM Permissions

The IAM role (`GitHubActions-InfraFleet`) is automatically created with permissions for:
- EKS cluster management
- EC2/VPC resources (for EKS nodes)
- IAM roles (for EKS service accounts)
- Auto Scaling, CloudWatch Logs, SSM
- Terraform state management (S3/DynamoDB if used)

**Defined in**: `infrastructure/permanent/github-oidc.tf` (permanent infrastructure, never destroyed)

## Kubernetes Resource Cleanup Script

**Current Version**: `scripts/cleanup-k8s-resources-v2.sh` (Hybrid Approach - 2025-11-26)
**Previous Version**: `scripts/cleanup-k8s-resources.sh` (Kubernetes-only - deprecated)

### Purpose

Kubernetes controllers (like ALB controller, EBS CSI driver) create AWS resources outside of Terraform's management. When Terraform destroys the EKS cluster, these controllers are killed before they can clean up their AWS resources, leading to **orphaned resources** that continue billing.

**Challenge**: If the cluster is already destroyed, Kubernetes-native cleanup cannot work. The hybrid approach solves this by using AWS API as a fallback.

### What It Cleans Up

1. **Ingress Resources** → Application Load Balancers
   - ALB controller creates ALBs when Ingress resources are deployed
   - Without cleanup: ALBs remain provisioned (~$17/month per ALB)
   - Also cleans: Target groups, security groups, listeners

2. **LoadBalancer Services** → Classic/Network Load Balancers
   - Cloud provider creates ELBs for Service type=LoadBalancer
   - Without cleanup: ELBs remain provisioned

3. **PersistentVolumeClaims** → EBS Volumes
   - EBS CSI driver provisions volumes for PVCs
   - Without cleanup: Volumes remain attached/provisioned

### How It Works (v2 Hybrid Approach)

```bash
# 1. Check if cluster exists and is healthy
if aws eks describe-cluster --name staging &>/dev/null; then
    CLEANUP_METHOD="kubernetes"
    # 2a. Kubernetes-native cleanup (preferred)
    aws eks update-kubeconfig --name staging --region eu-west-2
    flux suspend kustomization applications
    kubectl delete ingress --all -A --timeout=5m
    sleep 90  # Wait for ALB controller to delete ALBs
    kubectl delete svc --field-selector spec.type=LoadBalancer -A
    kubectl delete pvc --all -A --timeout=3m
else
    CLEANUP_METHOD="aws-tags"
fi

# 2b. AWS tag-based cleanup (always runs as fallback)
# Delete ALBs by elbv2.k8s.aws/cluster tag
ALB_ARNS=$(aws elbv2 describe-load-balancers --query 'LoadBalancers[*].LoadBalancerArn' --output text)
for alb_arn in $ALB_ARNS; do
    CLUSTER_TAG=$(aws elbv2 describe-tags --resource-arns "$alb_arn" \
        --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='staging'].Value" --output text)
    if [ -n "$CLUSTER_TAG" ]; then
        aws elbv2 delete-load-balancer --load-balancer-arn "$alb_arn"
    fi
done

# Delete ENIs by kubernetes.io/cluster tag
ENI_IDS=$(aws ec2 describe-network-interfaces \
    --filters "Name=tag:kubernetes.io/cluster/staging,Values=owned" \
    --query 'NetworkInterfaces[*].NetworkInterfaceId' --output text)
for eni_id in $ENI_IDS; do
    aws ec2 delete-network-interface --network-interface-id "$eni_id" 2>/dev/null || true
done

# 3. Verification (only fail for ALBs/ENIs, not Security Groups)
REMAINING_ALBS=$(count remaining ALBs)
REMAINING_ENIS=$(count remaining ENIs)
if [ "$REMAINING_ALBS" -gt 0 ] || [ "$REMAINING_ENIS" -gt 0 ]; then
    echo "❌ Critical resources remain - will block VPC deletion!"
    exit 1
else
    echo "✅ All critical resources cleaned (ALBs, ENIs)"
fi
```

**Key Improvements**:
- Works even if cluster already destroyed
- Dual cleanup strategy (Kubernetes + AWS API)
- Only fails for resources that truly block VPC deletion
- Detailed logging and verification

### Usage

**Automated** (in workflows):
```yaml
- name: Clean up Kubernetes resources (v2 hybrid)
  run: |
    chmod +x scripts/cleanup-k8s-resources-v2.sh
    ./scripts/cleanup-k8s-resources-v2.sh staging eu-west-2
```

**Manual** (if needed):
```bash
# From repository root (v2 hybrid approach)
./scripts/cleanup-k8s-resources-v2.sh staging eu-west-2

# Or dry-run mode (see what would be deleted)
./scripts/cleanup-k8s-resources-v2.sh staging eu-west-2 dry-run

# Or manual Kubernetes cleanup (if cluster is healthy)
aws eks update-kubeconfig --name staging --region eu-west-2
flux suspend kustomization applications
kubectl delete ingress --all -A
```

### Error Handling

The script is **idempotent** and handles:
- ✅ Cluster doesn't exist (already destroyed)
- ✅ Cluster exists but is unhealthy (skip cleanup)
- ✅ No resources to clean (skip that step)
- ✅ Partial failures (continue with destroy)

## Usage Guide

### Starting Fresh (After Nightly Destruction)

1. **Go to GitHub Actions**
2. **Select "Rebuild Stack (Manual)" workflow**
3. **Click "Run workflow"**
4. **Optional**: Provide reason for rebuild
5. **Wait**: ~25-30 minutes for completion
6. **Resume work**: Check `ai/CLAUDE.md` for context

### Emergency Override

To skip nightly destruction (emergency use only):

```bash
touch .nodestroytonight
git add .nodestroytonight
git commit -m "Emergency: Skip tonight's destruction"
git push
```

### Monitoring Costs

- **CloudWatch**: Monitor daily costs in AWS billing
- **Expected Pattern**: $0 overnight, ~$6-8 during usage days
- **Monthly Target**: $50-70 total vs $144 continuous

## Troubleshooting

### Rebuild Fails

1. **Check GitHub Actions logs** for specific error
2. **Verify AWS credentials** are valid and have permissions
3. **Check main branch health** - all tests must pass
4. **Manual intervention**: Use AWS Console if needed

### Destruction Incomplete

1. **Check AWS Console** for any remaining resources
2. **Manual cleanup**: Delete resources via AWS Console
3. **Verify billing** to ensure no unexpected charges

### Flux SSH Authentication Error During Destroy

**Symptoms**:
```
Error: Could not delete Flux configuration from Git repository.
ssh: handshake failed: ssh: unable to authenticate
```

**Cause**: Terraform trying to clean up Flux Git commits, but SSH key already destroyed.

**Solution**:
1. Ensure `delete_git_manifests = false` is set in `infrastructure/staging/flux.tf`
2. If stuck in failed destroy, remove Flux from state:
   ```bash
   cd infrastructure/staging
   terraform state rm flux_bootstrap_git.this
   terraform destroy -auto-approve
   ```

**Prevention**: PR #32 adds `delete_git_manifests = false` to prevent this issue.

### Orphaned ALBs After Destroy

**Symptoms**: ALBs remain in AWS Console after destroy, continuing to bill (~$17/month).

**Cause**: Kubernetes controllers create ALBs that aren't tracked by Terraform.

**Solution**:
1. **Automated** (preferred): Cleanup script handles this automatically
2. **Manual cleanup**:
   ```bash
   # List orphaned ALBs
   aws elbv2 describe-load-balancers --region eu-west-2 \
     --query 'LoadBalancers[?contains(LoadBalancerName, `k8s`)].LoadBalancerArn'

   # Delete manually
   aws elbv2 delete-load-balancer --load-balancer-arn <ARN>
   ```

**Prevention**: PR #31 adds Flux suspension to prevent race condition.

### Flux Recreating Resources During Cleanup

**Symptoms**: Resources deleted by cleanup script reappear before destroy completes.

**Cause**: Flux reconciles every ~1 minute and recreates missing resources.

**Solution**: Cleanup script automatically suspends Flux (`flux suspend kustomization applications`).

**Manual fix** (if needed):
```bash
flux suspend kustomization applications
./scripts/cleanup-k8s-resources.sh staging eu-west-2
# Then run destroy
```

### Terraform Version Mismatch

**Symptoms**:
```
Error: Incompatible Terraform version
The local Terraform version (1.12.2) does not meet the version requirements
for remote workspace your-terraform-org/infra-fleet-staging (~> 1.14.0).
```

**Cause**: Local Terraform version differs from Terraform Cloud workspace setting.

**Solution**:
1. **Option A**: Upgrade local Terraform: `brew upgrade terraform`
2. **Option B**: Change TFC workspace version via UI to match local
3. **Emergency**: Use `-ignore-remote-version` flag (not recommended)

**Tracking**: Issue #33 documents version standardization.

### ALB Controller Has No Credentials

**Symptoms**: ALB controller logs show `NoCredentialProviders` errors.

**Cause**: Pod Identity association exists, but pod started before credentials available.

**Solution**: Restart the ALB controller deployment:
```bash
kubectl rollout restart deployment aws-load-balancer-controller -n kube-system
```

**Wait** for new pod to start, then check logs - should see no credential errors.

### Context Recovery

All context is preserved in `ai/` directory:
- `ai/CLAUDE.md` - Complete session context
- `ai/destruction-log.md` - Destruction/rebuild history
- `ai/last-*-state.*` - Infrastructure state snapshots

## Best Practices

### Daily Workflow

1. **Morning**: Trigger rebuild when ready to work
2. **Development**: Full development experience as normal
3. **Evening**: Commit all work, push to git
4. **Automatic**: Stack destroys at 8 PM UTC (hard stop for work day)

### Cost Management

- **Work in batches**: Rebuild only when needed
- **Weekend breaks**: Let destruction happen, zero costs
- **Monitor usage**: Track patterns and optimize further

### Development Continuity

- **Commit frequently**: Preserve work before destruction
- **Use context**: `ai/CLAUDE.md` maintains full project context
- **Document progress**: Update context for future sessions

## Testing Status (2025-11-21)

### Production Ready ✅

**Status**: Full end-to-end testing completed successfully

### Issues Discovered & Resolved

#### 1. Flux Race Condition (Issue #30, PR #31)
**Problem**: Flux would recreate deleted Kubernetes resources during cleanup, causing orphaned ALBs.
**Solution**: Cleanup script now suspends Flux before deleting resources.
**Testing**: Verified suspension prevents recreation for 2+ minutes.

#### 2. Flux Destroy SSH Authentication Error (PR #32)
**Problem**: Terraform destroy failed with SSH authentication error during Flux Git cleanup.
**Root Cause**: SSH private key destroyed before Flux provider could clean up Git commits.
**Solution**: Added `delete_git_manifests = false` to skip Git cleanup on destroy.
**Testing**: Destroy completed successfully (42 resources destroyed), no authentication errors.

#### 3. Terraform Version Mismatch (Issue #33)
**Problem**: Local Terraform (1.12.2) vs Terraform Cloud workspace (1.14.0).
**Impact**: Blocked emergency state manipulation during destroy recovery.
**Solution**: Temporarily aligned TFC workspace to 1.12.0.
**Follow-up**: Issue tracks long-term version standardization.

#### 4. ALB Controller Credentials (Discovered during testing)
**Problem**: ALB controller pod had no AWS credentials after deployment.
**Root Cause**: Pod Identity association created, but pod needed restart to pick up credentials.
**Solution**: Documented that Pod Identity requires pod restart after association creation.
**Note**: Not a workflow issue - resolved during initial testing.

### End-to-End Test Results (2025-11-21)

**Test Sequence**:
1. ✅ Merged PR #31 (Flux suspension)
2. ✅ Resumed Flux → Ingress recreated (proves race condition would occur)
3. ✅ Ran cleanup script → Flux suspended, resources deleted
4. ✅ Waited 2+ minutes → No resource recreation (Flux suspension working)
5. ✅ Verified no orphaned AWS resources (ALBs, Target Groups, Security Groups, EBS)
6. ✅ Local Terraform destroy → Completed successfully (42 resources)
7. ✅ Merged PR #32 (Flux Git cleanup fix)
8. ✅ CI rerun → Passed with clean state

**Resources Verified Clean**:
- ✅ No Application Load Balancers
- ✅ No Target Groups
- ✅ No Security Groups (k8s-created)
- ✅ No EBS Volumes (PVCs)
- ✅ No VPCs
- ✅ No GitHub Deploy Keys
- ✅ EKS Cluster deleted

### Outstanding Items

**Non-blocking**:
- Issue #30: Long-term GitOps patterns for ephemeral infrastructure (research)
- Issue #33: Terraform version standardization (process improvement)
- Issue #34: Post-destroy verification script (enhancement)
- Issue #28: Parameterization for sensitive data (enhancement)

### Next Milestones

1. ~~**Tonight (1 AM UTC)**: First automated nightly destroy with all fixes~~ ✅ **COMPLETED**
2. ~~**Tomorrow**: Test rebuild workflow after nightly destroy~~ ✅ **COMPLETED**
3. **Future**: Implement post-destroy verification script (Issue #34)

### Update: v3 Multi-Job Workflow (2025-11-26)

**Evolution**: Single-job workflow → v3 multi-job workflow with hybrid cleanup

**New Features**:
- ✅ 5 separate jobs for visual separation
- ✅ Hybrid cleanup approach (Kubernetes + AWS tag-based)
- ✅ Fail-fast behavior with conditional execution
- ✅ Idempotency support
- ✅ Fixed security group verification logic (only fail for ALBs/ENIs)
- ✅ Automatic GitHub issue creation on scheduled run failures

**Production Validation** (2 successful runs):
- Run #19717342525: All 5 jobs passed ✅
- Run #19716632431: All 5 jobs passed ✅

**Key Fix**: Security group verification now only fails for resources that truly block VPC deletion (ALBs with ENIs), not Security Groups managed by Terraform.

See `docs/workflow-cleanup-plan.md` and `docs/implementation-summary-hybrid-cleanup.md` for complete details.

---

**Note**: This system is designed for educational/development environments. Production workloads should use different strategies with high availability and persistent data requirements.

**Last Updated**: 2025-12-01
**Status**: Production ready - v3 multi-job workflow with hybrid cleanup approach