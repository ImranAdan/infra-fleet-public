module "vpc" {
  source = "terraform-aws-modules/vpc/aws"

  name = "my-vpc"
  cidr = "10.0.0.0/16"

  # Two AZ setup - minimum required by EKS for high availability
  azs = ["eu-west-2a", "eu-west-2b"]
  # Two private subnets for EKS worker nodes and Session Manager (EKS requirement)
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  # Two public subnets for ALB - ALBs require at least 2 subnets in different AZs
  public_subnets = ["10.0.101.0/24", "10.0.102.0/24"]

  # NAT Gateway enabled for EKS worker nodes to access internet (external registries, APIs, etc.)
  # Session Manager uses public subnet to avoid NAT Gateway costs for jumpbox traffic
  enable_nat_gateway = true
  single_nat_gateway = true
  # Enables DNS hostname resolution for instances in the VPC, which is required by EKS.
  enable_dns_hostnames = true

  # Subnet tags for AWS Load Balancer Controller
  # These tags enable the ALB controller to auto-discover subnets for load balancer provisioning
  public_subnet_tags = {
    "kubernetes.io/role/elb"                      = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"             = "1"
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }

  tags = local.common_tags
}

output "vpc_id" {
  description = "The ID of the VPC (used for parameterization via ConfigMap)"
  value       = module.vpc.vpc_id
}

output "aws_region" {
  description = "The AWS region (used for parameterization via ConfigMap)"
  value       = local.aws_region
}
