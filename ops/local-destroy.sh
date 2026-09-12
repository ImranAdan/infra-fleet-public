#!/usr/bin/env bash
#
# Local Stack Destroy Script
# Replicates the nightly-destroy workflow for local execution
#
# Usage:
#   ./ops/local-destroy.sh --confirm-staging-destroy [--force]
#
# Prerequisites:
#   - AWS credentials configured (aws sso login or environment variables)
#   - Terraform CLI installed
#   - kubectl installed
#
# Reads HCP Terraform identifiers from config.env. AWS credentials must already
# be available in the caller's shell.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$REPO_ROOT/config.env}"
AWS_REGION="eu-west-2"
CLUSTER_NAME="staging"
FORCE=""
CONFIRMED=false

for argument in "$@"; do
    case "$argument" in
        --confirm-staging-destroy) CONFIRMED=true ;;
        --force) FORCE=--force ;;
        *)
            echo "Usage: $0 --confirm-staging-destroy [--force]" >&2
            exit 2
            ;;
    esac
done

if [ "$CONFIRMED" != true ]; then
    echo "Refusing to destroy without --confirm-staging-destroy." >&2
    exit 2
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Missing $CONFIG_FILE. Copy config.example.env to config.env first." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$CONFIG_FILE"
set +a

if [ -z "${TF_CLOUD_ORGANIZATION:-}" ] || [ -z "${TF_WORKSPACE_STAGING:-}" ]; then
    echo "config.env must define TF_CLOUD_ORGANIZATION and TF_WORKSPACE_STAGING." >&2
    exit 1
fi

export TF_WORKSPACE="$TF_WORKSPACE_STAGING"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 LOCAL STACK DESTROY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cluster: $CLUSTER_NAME"
echo "Region:  $AWS_REGION"
echo "Date:    $(date)"
echo "AWS identity: $(aws sts get-caller-identity --query Arn --output text)"
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
