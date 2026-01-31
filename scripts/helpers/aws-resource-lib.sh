#!/bin/bash
# --------------------------------------------------------------------------------------------------
# aws-resource-lib.sh - Shared AWS Resource Discovery Functions
#
# This library provides common functions for discovering and counting AWS resources
# that are tagged by Kubernetes. Used by cleanup and verification scripts.
#
# Usage: source "$(dirname "$0")/helpers/aws-resource-lib.sh"
# --------------------------------------------------------------------------------------------------

# Discover ALBs managed by AWS Load Balancer Controller for a specific cluster
# Usage: discover_cluster_albs <cluster-name> <region>
# Returns: Space-separated list of ALB ARNs
discover_cluster_albs() {
    local cluster_name="$1"
    local region="$2"
    local matching_arns=""

    local alb_arns
    alb_arns=$(aws elbv2 describe-load-balancers \
        --region "$region" \
        --query 'LoadBalancers[*].LoadBalancerArn' \
        --output text 2>/dev/null || echo "")

    if [ -n "$alb_arns" ]; then
        for alb_arn in $alb_arns; do
            # Check for ALB controller tag (elbv2.k8s.aws/cluster)
            local cluster_tag
            cluster_tag=$(aws elbv2 describe-tags \
                --resource-arns "$alb_arn" \
                --region "$region" \
                --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$cluster_name'].Value" \
                --output text 2>/dev/null || echo "")

            if [ -n "$cluster_tag" ]; then
                matching_arns="$matching_arns $alb_arn"
            fi
        done
    fi

    echo "${matching_arns# }"
}

# Discover ENIs tagged with cluster ownership
# Usage: discover_cluster_enis <cluster-name> <region>
# Returns: Space-separated list of ENI IDs
discover_cluster_enis() {
    local cluster_name="$1"
    local region="$2"

    aws ec2 describe-network-interfaces \
        --region "$region" \
        --filters "Name=tag:kubernetes.io/cluster/$cluster_name,Values=owned" \
        --query 'NetworkInterfaces[*].NetworkInterfaceId' \
        --output text 2>/dev/null || echo ""
}

# Discover Security Groups tagged with cluster ownership
# Usage: discover_cluster_security_groups <cluster-name> <region>
# Returns: Space-separated list of Security Group IDs
discover_cluster_security_groups() {
    local cluster_name="$1"
    local region="$2"

    aws ec2 describe-security-groups \
        --region "$region" \
        --filters "Name=tag:kubernetes.io/cluster/$cluster_name,Values=owned" \
        --query 'SecurityGroups[*].GroupId' \
        --output text 2>/dev/null || echo ""
}

# Discover EBS Volumes tagged with cluster ownership
# Usage: discover_cluster_volumes <cluster-name> <region>
# Returns: Space-separated list of Volume IDs
discover_cluster_volumes() {
    local cluster_name="$1"
    local region="$2"

    aws ec2 describe-volumes \
        --region "$region" \
        --filters "Name=tag:kubernetes.io/cluster/$cluster_name,Values=owned" \
        --query 'Volumes[*].VolumeId' \
        --output text 2>/dev/null || echo ""
}

# Check if EKS cluster exists and get its status
# Usage: check_cluster_status <cluster-name> <region>
# Returns: "ACTIVE", "CREATING", "DELETING", or "NOT_FOUND"
check_cluster_status() {
    local cluster_name="$1"
    local region="$2"

    if ! aws eks describe-cluster --name "$cluster_name" --region "$region" &>/dev/null; then
        echo "NOT_FOUND"
        return
    fi

    aws eks describe-cluster \
        --name "$cluster_name" \
        --region "$region" \
        --query 'cluster.status' \
        --output text 2>/dev/null
}

# Check if EKS cluster is healthy and accessible via kubectl
# Usage: check_cluster_health <cluster-name> <region>
# Returns: "healthy", "unhealthy", or "not_found"
check_cluster_health() {
    local cluster_name="$1"
    local region="$2"
    local kubeconfig="${3:-/tmp/kubeconfig-check-$$}"

    local status
    status=$(check_cluster_status "$cluster_name" "$region")

    if [ "$status" == "NOT_FOUND" ]; then
        echo "not_found"
        return
    fi

    if [ "$status" != "ACTIVE" ]; then
        echo "unhealthy"
        return
    fi

    # Try to connect via kubectl
    if aws eks update-kubeconfig --name "$cluster_name" --region "$region" --kubeconfig "$kubeconfig" &>/dev/null; then
        if KUBECONFIG="$kubeconfig" kubectl cluster-info &>/dev/null; then
            rm -f "$kubeconfig"
            echo "healthy"
            return
        fi
    fi

    rm -f "$kubeconfig"
    echo "unhealthy"
}

# Count items in a space-separated list
# Usage: count_items "$list"
# Returns: Count as integer
count_items() {
    local items="$1"
    if [ -z "$items" ]; then
        echo "0"
    else
        echo "$items" | wc -w | tr -d ' '
    fi
}

# Get ALB name from ARN
# Usage: get_alb_name <alb-arn> <region>
get_alb_name() {
    local alb_arn="$1"
    local region="$2"

    aws elbv2 describe-load-balancers \
        --load-balancer-arns "$alb_arn" \
        --region "$region" \
        --query 'LoadBalancers[0].LoadBalancerName' \
        --output text 2>/dev/null
}

# Get ENI status
# Usage: get_eni_status <eni-id> <region>
get_eni_status() {
    local eni_id="$1"
    local region="$2"

    aws ec2 describe-network-interfaces \
        --network-interface-ids "$eni_id" \
        --region "$region" \
        --query 'NetworkInterfaces[0].Status' \
        --output text 2>/dev/null || echo "unknown"
}

# Get Security Group name
# Usage: get_sg_name <sg-id> <region>
get_sg_name() {
    local sg_id="$1"
    local region="$2"

    aws ec2 describe-security-groups \
        --group-ids "$sg_id" \
        --region "$region" \
        --query 'SecurityGroups[0].GroupName' \
        --output text 2>/dev/null || echo "unknown"
}

# Get Volume state
# Usage: get_volume_state <volume-id> <region>
get_volume_state() {
    local vol_id="$1"
    local region="$2"

    aws ec2 describe-volumes \
        --volume-ids "$vol_id" \
        --region "$region" \
        --query 'Volumes[0].State' \
        --output text 2>/dev/null || echo "unknown"
}

# Print resource summary
# Usage: print_resource_summary <alb-count> <eni-count> <sg-count> <vol-count>
print_resource_summary() {
    local alb_count="${1:-0}"
    local eni_count="${2:-0}"
    local sg_count="${3:-0}"
    local vol_count="${4:-0}"

    echo "   Resource Summary:"
    echo "      - ALBs: $alb_count"
    echo "      - ENIs: $eni_count"
    echo "      - Security Groups: $sg_count"
    echo "      - EBS Volumes: $vol_count"
}
