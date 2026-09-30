#!/bin/bash
# cleanup-k8s-resources-v2.sh
# HYBRID CLEANUP: Kubernetes-native + AWS tag-based fallback
# Cleans up Kubernetes-managed AWS resources before Terraform destroy
# This prevents orphaned load balancers, security groups, EBS volumes, and ENIs
#
# Strategy:
#   1. If cluster is healthy: Use Kubernetes API (GitOps-native cleanup)
#   2. If cluster is unhealthy/gone: Use AWS tags (fallback cleanup)
#   3. Verify all resources are deleted before returning
#
# Usage: ./cleanup-k8s-resources-v2.sh [cluster-name] [aws-region] [dry-run]
# Example: ./cleanup-k8s-resources-v2.sh staging eu-west-2
# Dry-run: ./cleanup-k8s-resources-v2.sh staging eu-west-2 dry-run

set -euo pipefail

CLUSTER_NAME="${1:-staging}"
AWS_REGION="${2:-eu-west-2}"
DRY_RUN="${3:-false}"

if [[ ! "$CLUSTER_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] ||
   [[ ! "$AWS_REGION" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$ ]]; then
    echo "Invalid EKS cluster name or AWS region." >&2
    exit 2
fi

case "$DRY_RUN" in
    false|live) DRY_RUN=false ;;
    dry-run) ;;
    *)
        echo "Mode must be dry-run or live." >&2
        exit 2
        ;;
esac

echo "🧹 Hybrid Kubernetes Resource Cleanup Script (v2)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cluster: $CLUSTER_NAME"
echo "Region: $AWS_REGION"
echo "Mode: $([ "$DRY_RUN" == "dry-run" ] && echo "DRY RUN (no changes)" || echo "LIVE (will delete resources)")"
echo "Date: $(date)"
echo ""

# Track cleanup status
CLEANUP_METHOD=""
FLUX_SUSPEND_FAILED=false

# =============================================================================
# Phase 1: Determine Cleanup Strategy
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Phase 1: Determining cleanup strategy..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if cluster exists
if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &>/dev/null; then
    CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --query 'cluster.status' --output text)
    echo "   ✅ Cluster found: $CLUSTER_NAME (Status: $CLUSTER_STATUS)"

    # Test cluster connectivity
    export KUBECONFIG="/tmp/kubeconfig-cleanup-$$"
    if aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --kubeconfig "$KUBECONFIG" &>/dev/null; then
        if kubectl cluster-info &>/dev/null; then
            echo "   ✅ Cluster is healthy and accessible"
            CLEANUP_METHOD="kubernetes"
        else
            echo "   ⚠️  Cluster exists but is not responding"
            CLEANUP_METHOD="aws-tags"
        fi
    else
        echo "   ⚠️  Cannot connect to cluster API"
        CLEANUP_METHOD="aws-tags"
    fi
else
    echo "   ⚠️  Cluster not found - may already be destroyed"
    CLEANUP_METHOD="aws-tags"
fi

echo ""
echo "   📋 Selected cleanup method: $CLEANUP_METHOD"
echo ""

# =============================================================================
# Phase 2a: Kubernetes-Native Cleanup (Preferred)
# =============================================================================
if [ "$CLEANUP_METHOD" == "kubernetes" ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🎯 Phase 2a: Kubernetes-Native Cleanup (GitOps Approach)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Step 0: Suspend every Flux Kustomization, including the root, so a
    # controller-owned Gateway Service cannot be recreated during teardown.
    echo "   ⏸️  Step 0: Suspending Flux reconciliation..."
    if [ "$DRY_RUN" == "dry-run" ]; then
        echo "      [DRY RUN] Would suspend all Flux Kustomizations:"
        kubectl get kustomizations.kustomize.toolkit.fluxcd.io -A \
            -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' \
            2>/dev/null | sed 's/^/         /'
    else
        if kubectl patch kustomizations.kustomize.toolkit.fluxcd.io --all -A \
            --type=merge -p '{"spec":{"suspend":true}}'; then
            echo "      ✅ Suspended all Flux Kustomizations"
            sleep 5
        else
            echo "      ⚠️  Could not suspend Flux Kustomizations; continuing cleanup"
            FLUX_SUSPEND_FAILED=true
        fi
    fi

    # Step 1: Delete Gateway API entry points. Envoy Gateway owns the generated
    # LoadBalancer Service, so remove its parent before falling back to direct
    # Service or ELBv2 deletion.
    echo ""
    echo "   🗑️  Step 1: Deleting Gateway API entry points..."
    GATEWAY_COUNT=$(kubectl get gateways.gateway.networking.k8s.io -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$GATEWAY_COUNT" -gt 0 ]; then
        echo "      Found: $GATEWAY_COUNT Gateway resource(s)"
        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "      [DRY RUN] Would delete:"
            kubectl get gateways.gateway.networking.k8s.io -A 2>/dev/null | sed 's/^/         /'
        else
            kubectl delete gateways.gateway.networking.k8s.io --all -A --timeout=5m || echo "      ⚠️  Some Gateway deletions failed"
            echo "      ⏳ Waiting 30 seconds for Envoy Gateway cleanup..."
            sleep 30
            echo "      ✅ Gateway deletion complete"
        fi
    else
        echo "      Found: 0 Gateway resources"
    fi

    # Step 2: Delete legacy Ingress resources if an older deployment left any.
    echo ""
    echo "   🗑️  Step 2: Deleting legacy Ingress resources..."
    INGRESS_COUNT=$(kubectl get ingress -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$INGRESS_COUNT" -gt 0 ]; then
        echo "      Found: $INGRESS_COUNT Ingress resource(s)"
        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "      [DRY RUN] Would delete:"
            kubectl get ingress -A 2>/dev/null | sed 's/^/         /'
        else
            kubectl delete ingress --all -A --timeout=5m || echo "      ⚠️  Some Ingress deletions failed"
            echo "      ⏳ Waiting 90 seconds for AWS Load Balancer Controller cleanup..."
            sleep 90
            echo "      ✅ Ingress deletion complete"
        fi
    else
        echo "      Found: 0 Ingress resources"
    fi

    # Step 3: Delete LoadBalancer Services
    echo ""
    echo "   🗑️  Step 3: Deleting LoadBalancer Services..."
    LB_SERVICES=$(kubectl get svc -A -o json 2>/dev/null | jq -r '.items[] | select(.spec.type=="LoadBalancer") | "\(.metadata.namespace)/\(.metadata.name)"' || echo "")
    if [ -n "$LB_SERVICES" ]; then
        LB_COUNT=$(echo "$LB_SERVICES" | wc -l | tr -d ' ')
        echo "      Found: $LB_COUNT LoadBalancer Service(s)"
        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "      [DRY RUN] Would delete:"
            printf '         %s\n' "${LB_SERVICES//$'\n'/$'\n         '}"
        else
            echo "$LB_SERVICES" | while IFS='/' read -r namespace name; do
                if [ -n "$namespace" ] && [ -n "$name" ]; then
                    echo "      Deleting $namespace/$name..."
                    kubectl delete svc -n "$namespace" "$name" --timeout=2m || echo "      ⚠️  Failed to delete $namespace/$name"
                fi
            done
            echo "      ⏳ Waiting 30 seconds for cloud provider cleanup..."
            sleep 30
            echo "      ✅ LoadBalancer Services deletion complete"
        fi
    else
        echo "      Found: 0 LoadBalancer Services"
    fi

    # Step 4: Delete PersistentVolumeClaims
    echo ""
    echo "   🗑️  Step 4: Deleting PersistentVolumeClaims..."
    PVC_COUNT=$(kubectl get pvc -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PVC_COUNT" -gt 0 ]; then
        echo "      Found: $PVC_COUNT PVC(s)"
        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "      [DRY RUN] Would delete:"
            kubectl get pvc -A 2>/dev/null | sed 's/^/         /'
        else
            kubectl delete pvc --all -A --timeout=3m || echo "      ⚠️  Some PVC deletions failed"
            echo "      ⏳ Waiting 20 seconds for EBS detachment..."
            sleep 20
            echo "      ✅ PVC deletion complete"
        fi
    else
        echo "      Found: 0 PVCs"
    fi

    # Cleanup kubeconfig
    rm -f "$KUBECONFIG"

    echo ""
    echo "   ✅ Kubernetes-native cleanup complete"
fi

# =============================================================================
# Phase 2b: AWS Tag-Based Cleanup (Fallback)
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Phase 2b: AWS Tag-Based Cleanup (Fallback)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   This handles orphaned resources even if cluster is gone"
echo ""

# Step 1: Delete ALBs or NLBs created by AWS Load Balancer Controller
echo "   🗑️  Step 1: Cleaning up ELBv2 load balancers..."
AWS_LB_ARNS=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" --query 'LoadBalancers[*].LoadBalancerArn' --output text 2>/dev/null || echo "")

AWS_LB_COUNT=0
if [ -n "$AWS_LB_ARNS" ]; then
    for aws_lb_arn in $AWS_LB_ARNS; do
        # Check for the AWS Load Balancer Controller cluster tag.
        CLUSTER_TAG=$(aws elbv2 describe-tags --resource-arns "$aws_lb_arn" --region "$AWS_REGION" --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$CLUSTER_NAME'].Value" --output text 2>/dev/null || echo "")

        if [ -n "$CLUSTER_TAG" ]; then
            AWS_LB_COUNT=$((AWS_LB_COUNT + 1))
            AWS_LB_NAME=$(aws elbv2 describe-load-balancers --load-balancer-arns "$aws_lb_arn" --region "$AWS_REGION" --query 'LoadBalancers[0].LoadBalancerName' --output text 2>/dev/null)
            AWS_LB_TYPE=$(aws elbv2 describe-load-balancers --load-balancer-arns "$aws_lb_arn" --region "$AWS_REGION" --query 'LoadBalancers[0].Type' --output text 2>/dev/null)
            echo "      Found: $AWS_LB_NAME [$AWS_LB_TYPE]"

            if [ "$DRY_RUN" == "dry-run" ]; then
                echo "         [DRY RUN] Would delete load balancer: $aws_lb_arn"
            else
                echo "         Deleting load balancer: $aws_lb_arn"
                aws elbv2 delete-load-balancer --load-balancer-arn "$aws_lb_arn" --region "$AWS_REGION" || echo "         ⚠️  Failed to delete load balancer"
            fi
        fi
    done
fi

if [ "$AWS_LB_COUNT" -eq 0 ]; then
    echo "      ✅ No orphaned load balancers found"
else
    echo "      Found: $AWS_LB_COUNT load balancer(s)"
    if [ "$DRY_RUN" != "dry-run" ]; then
        echo "      ⏳ Waiting 60 seconds for load balancer deletion to propagate..."
        sleep 60
    fi
fi

# Step 2: Delete orphaned ENIs
echo ""
echo "   🗑️  Step 2: Cleaning up Elastic Network Interfaces..."
ENI_IDS=$(aws ec2 describe-network-interfaces \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'NetworkInterfaces[*].NetworkInterfaceId' \
    --output text 2>/dev/null || echo "")

ENI_COUNT=0
if [ -n "$ENI_IDS" ]; then
    ENI_COUNT=$(echo "$ENI_IDS" | wc -w | tr -d ' ')
    echo "      Found: $ENI_COUNT ENI(s)"

    for eni_id in $ENI_IDS; do
        ENI_STATUS=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni_id" --region "$AWS_REGION" --query 'NetworkInterfaces[0].Status' --output text 2>/dev/null || echo "unknown")
        echo "      ENI: $eni_id (Status: $ENI_STATUS)"

        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "         [DRY RUN] Would delete ENI: $eni_id"
        else
            # Detach if attached
            if [ "$ENI_STATUS" == "in-use" ]; then
                ATTACHMENT_ID=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni_id" --region "$AWS_REGION" --query 'NetworkInterfaces[0].Attachment.AttachmentId' --output text 2>/dev/null || echo "")
                if [ -n "$ATTACHMENT_ID" ] && [ "$ATTACHMENT_ID" != "None" ]; then
                    echo "         Detaching ENI..."
                    aws ec2 detach-network-interface --attachment-id "$ATTACHMENT_ID" --region "$AWS_REGION" --force || echo "         ⚠️  Failed to detach"
                    sleep 10
                fi
            fi

            # Delete ENI
            echo "         Deleting ENI..."
            aws ec2 delete-network-interface --network-interface-id "$eni_id" --region "$AWS_REGION" || echo "         ⚠️  Failed to delete (may still be detaching)"
        fi
    done
else
    echo "      ✅ No orphaned ENIs found"
fi

# Step 3: Delete orphaned Security Groups (with retries)
echo ""
echo "   🗑️  Step 3: Cleaning up Security Groups..."
SG_DELETED=0

for attempt in {1..5}; do
    SG_IDS=$(aws ec2 describe-security-groups \
        --region "$AWS_REGION" \
        --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
        --query 'SecurityGroups[*].GroupId' \
        --output text 2>/dev/null || echo "")

    if [ -z "$SG_IDS" ]; then
        echo "      ✅ No orphaned Security Groups found"
        break
    fi

    SG_COUNT=$(echo "$SG_IDS" | wc -w | tr -d ' ')
    echo "      Attempt $attempt/5: Found $SG_COUNT Security Group(s)"

    for sg_id in $SG_IDS; do
        SG_NAME=$(aws ec2 describe-security-groups --group-ids "$sg_id" --region "$AWS_REGION" --query 'SecurityGroups[0].GroupName' --output text 2>/dev/null || echo "unknown")
        echo "         $sg_id ($SG_NAME)"

        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "            [DRY RUN] Would delete SG: $sg_id"
        else
            if aws ec2 delete-security-group --group-id "$sg_id" --region "$AWS_REGION" 2>/dev/null; then
                echo "            ✅ Deleted"
                SG_DELETED=$((SG_DELETED + 1))
            else
                echo "            ⚠️  Cannot delete yet (dependencies exist)"
            fi
        fi
    done

    if [ "$attempt" -lt 5 ] && [ "$DRY_RUN" != "dry-run" ]; then
        echo "      ⏳ Waiting 15 seconds before retry..."
        sleep 15
    fi
done

# Step 4: Delete orphaned EBS Volumes
echo ""
echo "   🗑️  Step 4: Cleaning up EBS Volumes..."
VOL_IDS=$(aws ec2 describe-volumes \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'Volumes[*].VolumeId' \
    --output text 2>/dev/null || echo "")

VOL_COUNT=0
if [ -n "$VOL_IDS" ]; then
    VOL_COUNT=$(echo "$VOL_IDS" | wc -w | tr -d ' ')
    echo "      Found: $VOL_COUNT EBS Volume(s)"

    for vol_id in $VOL_IDS; do
        VOL_STATE=$(aws ec2 describe-volumes --volume-ids "$vol_id" --region "$AWS_REGION" --query 'Volumes[0].State' --output text 2>/dev/null || echo "unknown")
        echo "      Volume: $vol_id (State: $VOL_STATE)"

        if [ "$DRY_RUN" == "dry-run" ]; then
            echo "         [DRY RUN] Would delete volume: $vol_id"
        else
            echo "         Deleting volume..."
            aws ec2 delete-volume --volume-id "$vol_id" --region "$AWS_REGION" || echo "         ⚠️  Failed to delete (may still be attached)"
        fi
    done
else
    echo "      ✅ No orphaned EBS Volumes found"
fi

# =============================================================================
# Phase 3: Verification
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Phase 3: Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$DRY_RUN" == "dry-run" ]; then
    echo "   ℹ️  DRY RUN mode - no actual changes made"
    echo "   Review the output above to see what would be deleted"
else
    echo "   🔍 Checking for remaining resources..."

    REMAINING_ISSUES=0
    if [ "$FLUX_SUSPEND_FAILED" == "true" ]; then
        echo "   ⚠️  Flux suspension failed; reconciliation may recreate resources"
        REMAINING_ISSUES=1
    fi

    # Check for remaining ELBv2 load balancers
    REMAINING_LBS=0
    AWS_LB_ARNS=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" --query 'LoadBalancers[*].LoadBalancerArn' --output text 2>/dev/null || echo "")
    if [ -n "$AWS_LB_ARNS" ]; then
        for aws_lb_arn in $AWS_LB_ARNS; do
            CLUSTER_TAG=$(aws elbv2 describe-tags --resource-arns "$aws_lb_arn" --region "$AWS_REGION" --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$CLUSTER_NAME'].Value" --output text 2>/dev/null || echo "")
            if [ -n "$CLUSTER_TAG" ]; then
                REMAINING_LBS=$((REMAINING_LBS + 1))
            fi
        done
    fi

    # Check for remaining ENIs
    REMAINING_ENIS=$(aws ec2 describe-network-interfaces \
        --region "$AWS_REGION" \
        --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
        --query 'NetworkInterfaces[*].NetworkInterfaceId' \
        --output text 2>/dev/null | wc -w | tr -d ' ')

    # Check for remaining SGs
    REMAINING_SGS=$(aws ec2 describe-security-groups \
        --region "$AWS_REGION" \
        --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
        --query 'SecurityGroups[*].GroupId' \
        --output text 2>/dev/null | wc -w | tr -d ' ')

    # Check for remaining EBS volumes
    REMAINING_VOLS=$(aws ec2 describe-volumes \
        --region "$AWS_REGION" \
        --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
        --query 'Volumes[*].VolumeId' \
        --output text 2>/dev/null | wc -w | tr -d ' ')

    echo "   Remaining resources:"
    echo "      - Load balancers: $REMAINING_LBS"
    echo "      - ENIs: $REMAINING_ENIS"
    echo "      - Security Groups: $REMAINING_SGS"
    echo "      - EBS Volumes: $REMAINING_VOLS"
    echo ""

    # Only fail if orphaned load balancers or ENIs remain (these block VPC deletion)
    # Security Groups are managed by Terraform and will be deleted during destroy
    if [ "$REMAINING_LBS" -gt 0 ] || [ "$REMAINING_ENIS" -gt 0 ]; then
        echo "   ⚠️  WARNING: Orphaned load balancers or ENIs detected!"
        echo "   This WILL cause Terraform destroy to fail"
        echo "   Check the logs above for details"
        REMAINING_ISSUES=1
    else
        echo "   ✅ All critical resources cleaned (load balancers, ENIs)"
        if [ "$REMAINING_SGS" -gt 0 ]; then
            echo "   ℹ️  Security Groups remain (will be deleted by Terraform)"
        fi
        if [ "$REMAINING_VOLS" -gt 0 ]; then
            echo "   ℹ️  EBS Volumes remain (will be deleted by Terraform)"
        fi
    fi
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Cleanup Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   Cleanup method: $CLEANUP_METHOD"
echo "   Mode: $([ "$DRY_RUN" == "dry-run" ] && echo "DRY RUN" || echo "LIVE")"
echo ""
echo "✅ Cleanup script complete"
if [ "$DRY_RUN" == "dry-run" ] || [ "${REMAINING_ISSUES:-0}" -eq 0 ]; then
    echo "✅ Safe to proceed with Terraform destroy"
else
    echo "⚠️  Cleanup needs attention before Terraform destroy"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Exit with appropriate code
if [ "$DRY_RUN" == "dry-run" ]; then
    exit 0
elif [ "${REMAINING_ISSUES:-0}" -eq 1 ]; then
    exit 1
else
    exit 0
fi
