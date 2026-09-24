# --------------------------------------------------------------------------------------------------
# Local Values
# Centralized local values used across the staging infrastructure stack.
# Data sources for AWS account are defined in outputs-configmap.tf
# --------------------------------------------------------------------------------------------------

locals {
  # Environment name - used for naming resources and tags
  environment = "staging"

  # Cluster name - used in EKS module and Kubernetes discovery tags
  cluster_name = "staging"

  # AWS configuration
  aws_account_id = data.aws_caller_identity.current.account_id
  aws_region     = "eu-west-2"

  # Common tags applied to all resources
  # Use: tags = local.common_tags or merge(local.common_tags, { Name = "..." })
  common_tags = {
    Terraform   = "true"
    Environment = local.environment
    ManagedBy   = "terraform"
  }

  # Cost-allocation tags the AWS provider applies to every taggable resource,
  # so billed usage can be split by environment, service and owner.
  cost_tags = {
    Environment = local.environment
    Service     = "infra-fleet"
    Owner       = var.cost_owner
  }
}
