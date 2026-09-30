#!/bin/bash
# verify-cleanup-resources.sh
# READ-ONLY script to verify what resources would be cleaned up
# This script does NOT delete anything - it only reports what it finds
#
#
# Usage: ./verify-cleanup-resources.sh [cluster-name] [aws-region]
# Example: ./verify-cleanup-resources.sh staging eu-west-2

set -euo pipefail

CLUSTER_NAME="${1:-staging}"
AWS_REGION="${2:-eu-west-2}"

if [[ ! "$CLUSTER_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] ||
   [[ ! "$AWS_REGION" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$ ]]; then
    echo "Invalid EKS cluster name or AWS region." >&2
    exit 2
fi

echo "🔍 Resource Discovery Report (READ-ONLY)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cluster: $CLUSTER_NAME"
echo "Region: $AWS_REGION"
echo "Date: $(date)"
echo ""

# =============================================================================
# Check 1: Cluster Status
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Check 1: EKS Cluster Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CLUSTER_HEALTHY=false

if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &>/dev/null; then
    CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" --query 'cluster.status' --output text)
    echo "   ✅ Cluster found: $CLUSTER_NAME"
    echo "   Status: $CLUSTER_STATUS"

    if [ "$CLUSTER_STATUS" == "ACTIVE" ]; then
        CLUSTER_HEALTHY=true
        echo "   ✅ Cluster is ACTIVE and healthy"
    else
        echo "   ⚠️  Cluster is not ACTIVE (status: $CLUSTER_STATUS)"
    fi
else
    echo "   ❌ Cluster NOT found: $CLUSTER_NAME"
    echo "   Will use AWS tag-based cleanup (fallback mode)"
fi

echo ""

# =============================================================================
# Check 2: Kubernetes Resources (if cluster is healthy)
# =============================================================================
if [ "$CLUSTER_HEALTHY" == true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 Check 2: Kubernetes Resources"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Configure kubectl
    export KUBECONFIG="/tmp/kubeconfig-verify-$$"
    if aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" --kubeconfig "$KUBECONFIG" &>/dev/null; then

        # Check Ingress resources
        echo ""
        echo "   🔍 Ingress Resources:"
        INGRESS_COUNT=$(kubectl get ingress -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [ "$INGRESS_COUNT" -gt 0 ]; then
            echo "   Found: $INGRESS_COUNT Ingress resource(s)"
            kubectl get ingress -A 2>/dev/null | sed 's/^/      /'
        else
            echo "   Found: 0 Ingress resources"
        fi

        # Check LoadBalancer Services
        echo ""
        echo "   🔍 LoadBalancer Services:"
        LB_SERVICES=$(kubectl get svc -A -o json 2>/dev/null | jq -r '.items[] | select(.spec.type=="LoadBalancer") | "\(.metadata.namespace)/\(.metadata.name)"' || echo "")
        if [ -n "$LB_SERVICES" ]; then
            LB_COUNT=$(echo "$LB_SERVICES" | wc -l | tr -d ' ')
            echo "   Found: $LB_COUNT LoadBalancer Service(s)"
            printf '      %s\n' "${LB_SERVICES//$'\n'/$'\n      '}"
        else
            echo "   Found: 0 LoadBalancer Services"
        fi

        # Check the Gateway API parents that own generated Envoy Services.
        echo ""
        echo "   🔍 Gateway resources:"
        GATEWAY_COUNT=$(kubectl get gateways.gateway.networking.k8s.io -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [ "$GATEWAY_COUNT" -gt 0 ]; then
            echo "   Found: $GATEWAY_COUNT Gateway resource(s)"
            kubectl get gateways.gateway.networking.k8s.io -A 2>/dev/null | sed 's/^/      /'
        else
            echo "   Found: 0 Gateway resources"
        fi

        # Check PVCs
        echo ""
        echo "   🔍 PersistentVolumeClaims:"
        PVC_COUNT=$(kubectl get pvc -A --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [ "$PVC_COUNT" -gt 0 ]; then
            echo "   Found: $PVC_COUNT PVC(s)"
            kubectl get pvc -A 2>/dev/null | sed 's/^/      /'
        else
            echo "   Found: 0 PVCs"
        fi

        # Check Flux Kustomizations
        echo ""
        echo "   🔍 Flux Kustomizations:"
        if kubectl get kustomizations -n flux-system &>/dev/null; then
            kubectl get kustomizations -n flux-system 2>/dev/null | sed 's/^/      /'
        else
            echo "   Flux not installed or not accessible"
        fi

        rm -f "$KUBECONFIG"
    else
        echo "   ⚠️  Could not connect to cluster"
    fi
fi

echo ""

# =============================================================================
# Check 3: AWS Resources Tagged by Kubernetes
# =============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Check 3: AWS Resources (Tagged by Kubernetes)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check for VPC
echo ""
echo "   🔍 VPC:"
VPC_ID=$(aws ec2 describe-vpcs \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=shared,owned" \
    --query 'Vpcs[0].VpcId' \
    --output text 2>/dev/null || echo "")

if [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
    echo "   Found: $VPC_ID"
else
    echo "   Found: 0 VPCs tagged with cluster name"
fi

# Check for ELBv2 load balancers (ALB or NLB)
echo ""
echo "   🔍 ELBv2 load balancers:"
AWS_LB_ARNS=$(aws elbv2 describe-load-balancers \
    --region "$AWS_REGION" \
    --query 'LoadBalancers[*].LoadBalancerArn' \
    --output text 2>/dev/null || echo "")

AWS_LB_COUNT=0
if [ -n "$AWS_LB_ARNS" ]; then
    for aws_lb_arn in $AWS_LB_ARNS; do
        # AWS Load Balancer Controller applies this cluster ownership tag to
        # both Application and Network Load Balancers.
        TAGS=$(aws elbv2 describe-tags --resource-arns "$aws_lb_arn" --region "$AWS_REGION" --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$CLUSTER_NAME'].Value" --output text 2>/dev/null || echo "")
        if [ -n "$TAGS" ]; then
            AWS_LB_COUNT=$((AWS_LB_COUNT + 1))
            AWS_LB_NAME=$(aws elbv2 describe-load-balancers --load-balancer-arns "$aws_lb_arn" --region "$AWS_REGION" --query 'LoadBalancers[0].LoadBalancerName' --output text 2>/dev/null)
            AWS_LB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$aws_lb_arn" --region "$AWS_REGION" --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null)
            AWS_LB_TYPE=$(aws elbv2 describe-load-balancers --load-balancer-arns "$aws_lb_arn" --region "$AWS_REGION" --query 'LoadBalancers[0].Type' --output text 2>/dev/null)
            echo "      - $AWS_LB_NAME [$AWS_LB_TYPE] ($AWS_LB_DNS)"
        fi
    done
fi
echo "   Found: $AWS_LB_COUNT load balancer(s) managed by Kubernetes"

# Check for ENIs
echo ""
echo "   🔍 Elastic Network Interfaces (ENIs):"
ENI_IDS=$(aws ec2 describe-network-interfaces \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'NetworkInterfaces[*].NetworkInterfaceId' \
    --output text 2>/dev/null || echo "")

ENI_COUNT=0
if [ -n "$ENI_IDS" ]; then
    ENI_COUNT=$(echo "$ENI_IDS" | wc -w | tr -d ' ')
    echo "   Found: $ENI_COUNT ENI(s)"
    for eni_id in $ENI_IDS; do
        ENI_STATUS=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni_id" --region "$AWS_REGION" --query 'NetworkInterfaces[0].Status' --output text 2>/dev/null)
        ENI_DESC=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni_id" --region "$AWS_REGION" --query 'NetworkInterfaces[0].Description' --output text 2>/dev/null)
        echo "      - $eni_id (Status: $ENI_STATUS, Desc: $ENI_DESC)"
    done
else
    echo "   Found: 0 ENIs"
fi

# Check for Security Groups
echo ""
echo "   🔍 Security Groups:"
SG_IDS=$(aws ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'SecurityGroups[*].GroupId' \
    --output text 2>/dev/null || echo "")

SG_COUNT=0
if [ -n "$SG_IDS" ]; then
    SG_COUNT=$(echo "$SG_IDS" | wc -w | tr -d ' ')
    echo "   Found: $SG_COUNT Security Group(s)"
    for sg_id in $SG_IDS; do
        SG_NAME=$(aws ec2 describe-security-groups --group-ids "$sg_id" --region "$AWS_REGION" --query 'SecurityGroups[0].GroupName' --output text 2>/dev/null)
        echo "      - $sg_id ($SG_NAME)"
    done
else
    echo "   Found: 0 Security Groups"
fi

# Check for EBS Volumes
echo ""
echo "   🔍 EBS Volumes:"
VOL_IDS=$(aws ec2 describe-volumes \
    --region "$AWS_REGION" \
    --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
    --query 'Volumes[*].VolumeId' \
    --output text 2>/dev/null || echo "")

VOL_COUNT=0
if [ -n "$VOL_IDS" ]; then
    VOL_COUNT=$(echo "$VOL_IDS" | wc -w | tr -d ' ')
    echo "   Found: $VOL_COUNT EBS Volume(s)"
    for vol_id in $VOL_IDS; do
        VOL_STATUS=$(aws ec2 describe-volumes --volume-ids "$vol_id" --region "$AWS_REGION" --query 'Volumes[0].State' --output text 2>/dev/null)
        VOL_SIZE=$(aws ec2 describe-volumes --volume-ids "$vol_id" --region "$AWS_REGION" --query 'Volumes[0].Size' --output text 2>/dev/null)
        echo "      - $vol_id (Status: $VOL_STATUS, Size: ${VOL_SIZE}GB)"
    done
else
    echo "   Found: 0 EBS Volumes"
fi

# =============================================================================
# Summary & Recommendations
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "   Cleanup Strategy Recommendation:"
if [ "$CLUSTER_HEALTHY" == true ]; then
    echo "   ✅ Use GitOps-native cleanup (Option D)"
    echo "      - Cluster is healthy"
    echo "      - Can use Flux/Kubernetes deletion"
    echo "      - AWS Load Balancer Controller will clean up AWS resources"
else
    echo "   ⚠️  Use AWS tag-based cleanup (Option A)"
    echo "      - Cluster is not available/healthy"
    echo "      - Must manually delete AWS resources by tags"
fi

echo ""
echo "   Resources that will be cleaned:"
echo "      - Load balancers: $AWS_LB_COUNT"
echo "      - ENIs: $ENI_COUNT"
echo "      - Security Groups: $SG_COUNT"
echo "      - EBS Volumes: $VOL_COUNT"

if [ "$CLUSTER_HEALTHY" == true ]; then
    echo "      - Ingress resources: $INGRESS_COUNT"
    echo "      - Gateway resources: ${GATEWAY_COUNT:-0}"
    echo "      - LoadBalancer Services: ${LB_COUNT:-0}"
    echo "      - PVCs: $PVC_COUNT"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Resource discovery complete (no changes made)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
