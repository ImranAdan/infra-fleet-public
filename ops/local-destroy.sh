#!/usr/bin/env bash
#
# Local Stack Destroy Script
# Replicates the nightly-destroy workflow for local execution
#
# Usage:
#   ./ops/local-destroy.sh [--force]
#
# Prerequisites:
#   - AWS credentials configured (aws sso login or environment variables)
#   - Terraform CLI installed
#   - kubectl installed
#
# Environment Variables (optional):
#   AWS_REGION     - AWS region (default: eu-west-2)
#   CLUSTER_NAME   - EKS cluster name (default: staging)
#   TF_VAR_grafana_admin_password - Grafana password (can be any value for destroy)
#

set -euo pipefail

# Configuration
AWS_REGION="${AWS_REGION:-eu-west-2}"
CLUSTER_NAME="${CLUSTER_NAME:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FORCE="${1:-}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 LOCAL STACK DESTROY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cluster: $CLUSTER_NAME"
echo "Region:  $AWS_REGION"
echo "Date:    $(date)"
echo ""

# ============================================================================
# Phase 1: Pre-verification
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Phase 1: Pre-Destroy Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CLUSTER_EXISTS=false
if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &>/dev/null; then
    echo "✅ Cluster found: $CLUSTER_NAME"
    CLUSTER_EXISTS=true
else
    echo "ℹ️  Cluster not found - may already be destroyed"
fi

# ============================================================================
# Phase 2: Kubernetes Resource Cleanup
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧹 Phase 2: Kubernetes Resource Cleanup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$CLUSTER_EXISTS" = true ]; then
    # Update kubeconfig
    echo "Updating kubeconfig..."
    aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"

    # Run cleanup script
    CLEANUP_SCRIPT="$REPO_ROOT/scripts/cleanup-k8s-resources-v2.sh"
    if [ -f "$CLEANUP_SCRIPT" ]; then
        chmod +x "$CLEANUP_SCRIPT"
        "$CLEANUP_SCRIPT" "$CLUSTER_NAME" "$AWS_REGION"
    else
        echo "⚠️  Cleanup script not found: $CLEANUP_SCRIPT"
        echo "   Skipping Kubernetes cleanup..."
    fi
else
    echo "ℹ️  Skipping Kubernetes cleanup (cluster not found)"
fi

# ============================================================================
# Phase 3: Post-Cleanup Verification
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Phase 3: Post-Cleanup Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check for orphaned ALBs
ALB_COUNT=0
ALB_ARNS=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" \
    --query 'LoadBalancers[*].LoadBalancerArn' --output text 2>/dev/null || echo "")

if [ -n "$ALB_ARNS" ]; then
    for alb_arn in $ALB_ARNS; do
        CLUSTER_TAG=$(aws elbv2 describe-tags --resource-arns "$alb_arn" \
            --region "$AWS_REGION" \
            --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$CLUSTER_NAME'].Value" \
            --output text 2>/dev/null || echo "")
        if [ -n "$CLUSTER_TAG" ]; then
            ALB_COUNT=$((ALB_COUNT + 1))
        fi
    done
fi

# Check for orphaned ENIs
ENI_COUNT=$(aws ec2 describe-network-interfaces \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'NetworkInterfaces[*].NetworkInterfaceId' \
    --output text 2>/dev/null | wc -w | tr -d ' ')

echo "Remaining orphaned resources:"
echo "  - ALBs: $ALB_COUNT"
echo "  - ENIs: $ENI_COUNT"

if [ "$ALB_COUNT" -gt 0 ] || [ "$ENI_COUNT" -gt 0 ]; then
    echo ""
    echo "❌ Orphaned resources detected!"
    if [ "$FORCE" != "--force" ]; then
        echo "   Terraform destroy may fail. Use --force to proceed anyway."
        exit 1
    else
        echo "   --force specified, proceeding anyway..."
    fi
else
    echo "✅ All critical resources cleaned - safe to proceed"
fi

# ============================================================================
# Phase 4: Terraform Destroy
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 Phase 4: Terraform Destroy"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⚠️  DESTROYING: Ephemeral infrastructure (infrastructure/staging/)"
echo "✅ PRESERVING: Permanent infrastructure (infrastructure/permanent/)"
echo ""

cd "$REPO_ROOT/infrastructure/staging"

# Set a dummy grafana password if not set (required by variable but not used for destroy)
export TF_VAR_grafana_admin_password="${TF_VAR_grafana_admin_password:-destroy-placeholder}"

terraform init -input=false
terraform destroy -auto-approve

# ============================================================================
# Phase 5: Final Verification
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Phase 5: Final Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if cluster exists
if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &>/dev/null; then
    echo "⚠️  WARNING: Cluster still exists!"
else
    echo "✅ Cluster destroyed"
fi

# Check for VPC
VPC_ID=$(aws ec2 describe-vpcs \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=shared,owned" \
    --query 'Vpcs[0].VpcId' \
    --output text 2>/dev/null || echo "")

if [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
    echo "⚠️  WARNING: VPC still exists: $VPC_ID"
else
    echo "✅ VPC destroyed"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ LOCAL DESTROY COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
