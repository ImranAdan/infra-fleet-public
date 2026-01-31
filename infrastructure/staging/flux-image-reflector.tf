# --------------------------------------------------------------------------------------------------
# Flux Image Reflector Controller - IAM Resources
#
# Terraform manages AWS resources (IAM role, policy, pod identity association).
# Enables image-reflector-controller to scan ECR for new container images.
#
# This is required for Flux Image Automation to work with private ECR registries.
# The controller needs ECR read permissions to discover available image tags.
# --------------------------------------------------------------------------------------------------

# IAM policy for Flux Image Reflector Controller
# Grants read-only access to ECR (required to scan for new images)
resource "aws_iam_policy" "flux_image_reflector" {
  name        = "FluxImageReflectorPolicy-${module.eks.cluster_name}"
  description = "IAM policy for Flux Image Reflector Controller to read ECR"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:GetRepositoryPolicy"
        ]
        Resource = "arn:aws:ecr:${local.aws_region}:${local.aws_account_id}:repository/load-harness"
      }
    ]
  })

  tags = local.common_tags
}

# IAM role and Pod Identity association for Flux Image Reflector Controller
# Only depends on Pod Identity agent - NOT on flux_bootstrap_git
# This allows the association to be created BEFORE Flux bootstrap,
# so the pod starts with credentials already available.
# See: https://github.com/your-org/infra-fleet/issues/159
module "flux_image_reflector_role" {
  source = "./modules/eks-pod-identity-role"

  role_name       = "FluxImageReflectorRole-${module.eks.cluster_name}"
  cluster_name    = module.eks.cluster_name
  namespace       = "flux-system"
  service_account = "image-reflector-controller"
  policy_arns     = [aws_iam_policy.flux_image_reflector.arn]
  tags            = local.common_tags

  depends_on = [aws_eks_addon.eks_pod_identity_agent]
}

output "flux_image_reflector_role_arn" {
  description = "ARN of the IAM role for Flux Image Reflector Controller"
  value       = module.flux_image_reflector_role.role_arn
}
