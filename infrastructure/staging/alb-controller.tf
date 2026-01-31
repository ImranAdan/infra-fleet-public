# --------------------------------------------------------------------------------------------------
# AWS Load Balancer Controller - IAM Resources
#
# Terraform manages AWS resources (IAM role, policy).
# Kubernetes deployment managed by Flux HelmRelease in k8s/infrastructure/aws-load-balancer-controller/
#
# Architecture decision: Keep AWS resources in Terraform, K8s resources in Flux (GitOps).
# See docs/Platform-Build-Roadmap.md for architectural guidance.
# --------------------------------------------------------------------------------------------------

# Data source for AWS Load Balancer Controller IAM policy
# Using main branch for latest policy (includes ec2:GetSecurityGroupsForVpc required for controller v2.7+)
data "http" "alb_controller_policy" {
  url = "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json"
}

resource "aws_iam_policy" "alb_controller" {
  name        = "AWSLoadBalancerControllerIAMPolicy-${module.eks.cluster_name}"
  description = "IAM policy for AWS Load Balancer Controller"
  policy      = data.http.alb_controller_policy.response_body

  tags = local.common_tags
}

# IAM role and Pod Identity association for AWS Load Balancer Controller
module "alb_controller_role" {
  source = "./modules/eks-pod-identity-role"

  role_name       = "AmazonEKSLoadBalancerControllerRole-${module.eks.cluster_name}"
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  policy_arns     = [aws_iam_policy.alb_controller.arn]
  tags            = local.common_tags

  depends_on = [aws_eks_addon.eks_pod_identity_agent]
}

output "alb_controller_role_arn" {
  description = "ARN of the IAM role for AWS Load Balancer Controller"
  value       = module.alb_controller_role.role_arn
}

output "alb_controller_policy_arn" {
  description = "ARN of the IAM policy for AWS Load Balancer Controller"
  value       = aws_iam_policy.alb_controller.arn
}
