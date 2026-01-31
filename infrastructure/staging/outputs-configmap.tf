# --------------------------------------------------------------------------------------------------
# Terraform Outputs for Flux Variable Substitution
#
# These outputs are used by the rebuild-stack.yml workflow to create the terraform-outputs
# ConfigMap in Kubernetes. Flux uses this ConfigMap for variable substitution in GitOps manifests.
#
# Previously, this file contained a kubernetes_config_map resource that required the Kubernetes
# provider. This was removed because the provider requires a live cluster to initialize, which
# caused terraform plan/apply to fail when the cluster was down.
#
# The ConfigMap is now created via kubectl in the rebuild-stack.yml workflow.
#
# History: Parameterization implemented via Issues #63, #28 (both resolved)
# --------------------------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Note: vpc_id, aws_region, and cluster_name outputs are already defined in vpc.tf and eks.tf

output "aws_account_id" {
  description = "AWS account ID for Flux variable substitution"
  value       = data.aws_caller_identity.current.account_id
}

output "ecr_registry" {
  description = "ECR registry URL for Flux variable substitution"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.id}.amazonaws.com"
}
