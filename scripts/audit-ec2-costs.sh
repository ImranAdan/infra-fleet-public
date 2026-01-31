#!/bin/bash
# Script to audit what's contributing to "EC2-Other" costs
# Run this after stack is built to see what resources exist

set -e

AWS_REGION="${1:-eu-west-2}"
CLUSTER_NAME="${2:-staging}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "EC2-Other Cost Audit"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Region: $AWS_REGION"
echo "Cluster: $CLUSTER_NAME"
echo ""

# 1. EBS Volumes
echo "━━━ 1. EBS VOLUMES ━━━"
echo ""
echo "Active EBS Volumes:"
aws ec2 describe-volumes \
  --region "$AWS_REGION" \
  --query 'Volumes[*].[VolumeId,Size,State,VolumeType,Iops,CreateTime,Tags[?Key==`Name`].Value|[0]]' \
  --output table

echo ""
echo "Cost estimate (active volumes):"
VOLUMES=$(aws ec2 describe-volumes --region "$AWS_REGION" --query 'Volumes[?State==`in-use`]' --output json)
TOTAL_SIZE=$(echo "$VOLUMES" | jq '[.[].Size] | add // 0')
echo "  Total size: ${TOTAL_SIZE} GB"
echo "  GP3 cost: \$$(echo "$TOTAL_SIZE * 0.08" | bc) per month"
echo ""

echo "Available (unattached) volumes that may be orphaned:"
aws ec2 describe-volumes \
  --region "$AWS_REGION" \
  --filters "Name=status,Values=available" \
  --query 'Volumes[*].[VolumeId,Size,CreateTime]' \
  --output table

# 2. EBS Snapshots
echo ""
echo "━━━ 2. EBS SNAPSHOTS ━━━"
echo ""
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "EBS Snapshots owned by account ${ACCOUNT_ID}:"
aws ec2 describe-snapshots \
  --region "$AWS_REGION" \
  --owner-ids "$ACCOUNT_ID" \
  --query 'Snapshots[*].[SnapshotId,VolumeSize,StartTime,Description]' \
  --output table

SNAP_COUNT=$(aws ec2 describe-snapshots --region "$AWS_REGION" --owner-ids "$ACCOUNT_ID" --query 'length(Snapshots)' --output text)
SNAP_SIZE=$(aws ec2 describe-snapshots --region "$AWS_REGION" --owner-ids "$ACCOUNT_ID" --query 'sum(Snapshots[*].VolumeSize)' --output text)
echo ""
echo "Snapshot summary:"
echo "  Count: $SNAP_COUNT"
echo "  Total size: ${SNAP_SIZE} GB"
echo "  Cost estimate: \$$(echo "$SNAP_SIZE * 0.05" | bc) per month"
echo ""

# 3. Elastic IPs
echo "━━━ 3. ELASTIC IPs ━━━"
echo ""
echo "Elastic IPs (cost \$0.005/hour = \$3.60/month each if unattached):"
aws ec2 describe-addresses \
  --region "$AWS_REGION" \
  --query 'Addresses[*].[PublicIp,AllocationId,AssociationId,Tags[?Key==`Name`].Value|[0]]' \
  --output table

UNATTACHED_EIPS=$(aws ec2 describe-addresses --region "$AWS_REGION" --query 'Addresses[?AssociationId==null]' --output json | jq length)
echo ""
echo "Unattached EIPs: $UNATTACHED_EIPS (costing \$$(echo "$UNATTACHED_EIPS * 3.60" | bc)/month)"
echo ""

# 4. NAT Gateway
echo "━━━ 4. NAT GATEWAYS ━━━"
echo ""
echo "NAT Gateways (\$0.045/hour = \$32.40/month each):"
aws ec2 describe-nat-gateways \
  --region "$AWS_REGION" \
  --filter "Name=state,Values=available" \
  --query 'NatGateways[*].[NatGatewayId,State,VpcId,SubnetId,Tags[?Key==`Name`].Value|[0]]' \
  --output table

NAT_COUNT=$(aws ec2 describe-nat-gateways --region "$AWS_REGION" --filter "Name=state,Values=available" --query 'length(NatGateways)' --output text)
echo ""
echo "Active NAT Gateways: $NAT_COUNT (costing \$$(echo "$NAT_COUNT * 32.40" | bc)/month base)"
echo ""

# 5. VPC Endpoints
echo "━━━ 5. VPC ENDPOINTS ━━━"
echo ""
echo "VPC Endpoints (Interface endpoints cost \$0.01/hour = \$7.20/month each):"
aws ec2 describe-vpc-endpoints \
  --region "$AWS_REGION" \
  --query 'VpcEndpoints[*].[VpcEndpointId,VpcEndpointType,ServiceName,State]' \
  --output table

INTERFACE_ENDPOINTS=$(aws ec2 describe-vpc-endpoints --region "$AWS_REGION" --query 'VpcEndpoints[?VpcEndpointType==`Interface`]' --output json | jq length)
echo ""
echo "Interface endpoints: $INTERFACE_ENDPOINTS (costing \$$(echo "$INTERFACE_ENDPOINTS * 7.20" | bc)/month)"
echo "Gateway endpoints: Free"
echo ""

# 6. Data Transfer (estimates only - need CloudWatch for actual)
echo "━━━ 6. DATA TRANSFER ━━━"
echo ""
echo "⚠️  Data transfer costs require CloudWatch metrics analysis"
echo "Common sources of data transfer charges:"
echo "  - NAT Gateway data processing: \$0.045/GB"
echo "  - VPC Endpoint data processing: \$0.01/GB"
echo "  - Inter-AZ data transfer: \$0.01/GB"
echo "  - Internet egress: \$0.09/GB (first 10TB)"
echo ""

# 7. Load Balancers
echo "━━━ 7. LOAD BALANCERS ━━━"
echo ""
echo "Application Load Balancers (\$0.0225/hour = \$16.20/month each):"
aws elbv2 describe-load-balancers \
  --region "$AWS_REGION" \
  --query 'LoadBalancers[*].[LoadBalancerName,Type,State.Code,CreatedTime,VpcId]' \
  --output table 2>/dev/null || echo "No ALBs found"

ALB_COUNT=$(aws elbv2 describe-load-balancers --region "$AWS_REGION" --query 'length(LoadBalancers)' --output text 2>/dev/null || echo "0")
echo ""
echo "Active ALBs: $ALB_COUNT (costing \$$(echo "$ALB_COUNT * 16.20" | bc)/month base + LCU charges)"
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "ESTIMATED MONTHLY COSTS (when stack is running 24/7)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "EBS Volumes:           \$$(echo "$TOTAL_SIZE * 0.08" | bc)"
echo "EBS Snapshots:         \$$(echo "$SNAP_SIZE * 0.05" | bc)"
echo "Unattached EIPs:       \$$(echo "$UNATTACHED_EIPS * 3.60" | bc)"
echo "NAT Gateways:          \$$(echo "$NAT_COUNT * 32.40" | bc)"
echo "Interface Endpoints:   \$$(echo "$INTERFACE_ENDPOINTS * 7.20" | bc)"
echo "ALBs:                  \$$(echo "$ALB_COUNT * 16.20" | bc) + LCU charges"
echo "Data Transfer:         (requires CloudWatch analysis)"
echo ""
echo "NOTE: These are estimates when stack runs 24/7."
echo "With nightly destroy, actual costs are much lower!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Usage: $0 [region] [cluster-name]"
echo "Example: $0 eu-west-2 staging"
echo ""
