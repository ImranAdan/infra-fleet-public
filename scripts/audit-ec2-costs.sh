#!/usr/bin/env bash
# Inventory AWS resources that commonly contribute to an infra-fleet bill.
# This script reports resources; it never deletes them or estimates prices.

set -euo pipefail

AWS_REGION=${1:-eu-west-2}
CLUSTER_NAME=${2:-staging}

command -v aws >/dev/null 2>&1 || {
  echo 'aws CLI is required.' >&2
  exit 1
}

account_id=$(aws sts get-caller-identity --query Account --output text)

cat <<EOF
Infra Fleet AWS resource inventory
Account: $account_id
Region:  $AWS_REGION
Cluster: $CLUSTER_NAME

EKS clusters
EOF
aws eks list-clusters \
  --region "$AWS_REGION" \
  --query 'clusters' \
  --output table

cat <<'EOF'

Running EC2 instances
EOF
# The backticks below are JMESPath literals, not shell interpolation.
# shellcheck disable=SC2016
aws ec2 describe-instances \
  --region "$AWS_REGION" \
  --filters 'Name=instance-state-name,Values=pending,running,stopping,stopped' \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PrivateIpAddress,Tags[?Key==`Name`].Value|[0]]' \
  --output table

cat <<'EOF'

EBS volumes
EOF
# shellcheck disable=SC2016
aws ec2 describe-volumes \
  --region "$AWS_REGION" \
  --query 'Volumes[].[VolumeId,Size,State,VolumeType,Attachments[0].InstanceId,Tags[?Key==`Name`].Value|[0]]' \
  --output table

cat <<'EOF'

Elastic IP addresses
EOF
# shellcheck disable=SC2016
aws ec2 describe-addresses \
  --region "$AWS_REGION" \
  --query 'Addresses[].[AllocationId,PublicIp,AssociationId,NetworkInterfaceId,Tags[?Key==`Name`].Value|[0]]' \
  --output table

cat <<'EOF'

NAT gateways
EOF
aws ec2 describe-nat-gateways \
  --region "$AWS_REGION" \
  --filter 'Name=state,Values=pending,available,deleting,failed' \
  --query 'NatGateways[].[NatGatewayId,State,VpcId,SubnetId,NatGatewayAddresses[0].PublicIp]' \
  --output table

cat <<'EOF'

VPC endpoints
EOF
aws ec2 describe-vpc-endpoints \
  --region "$AWS_REGION" \
  --query 'VpcEndpoints[].[VpcEndpointId,VpcEndpointType,ServiceName,State,VpcId]' \
  --output table

cat <<'EOF'

ELBv2 load balancers (application, network and gateway)
EOF
aws elbv2 describe-load-balancers \
  --region "$AWS_REGION" \
  --query 'LoadBalancers[].[LoadBalancerName,Type,Scheme,State.Code,VpcId,CreatedTime]' \
  --output table

cat <<'EOF'

Network interfaces owned by the selected Kubernetes cluster tag
EOF
aws ec2 describe-network-interfaces \
  --region "$AWS_REGION" \
  --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned,shared" \
  --query 'NetworkInterfaces[].[NetworkInterfaceId,Status,InterfaceType,VpcId,SubnetId,Description]' \
  --output table

cat <<'EOF'

ECR repositories
EOF
aws ecr describe-repositories \
  --region "$AWS_REGION" \
  --query 'repositories[].[repositoryName,imageTagMutability,createdAt]' \
  --output table

cat <<EOF

Inventory complete. Use Cost Explorer for current charges and verify tags and
ownership before removing any resource. The permanent ECR repository is
expected to remain after the $CLUSTER_NAME staging stack is destroyed.
EOF
