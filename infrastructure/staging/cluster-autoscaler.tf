# --------------------------------------------------------------------------------------------------
# Worker capacity: demand-driven scaling (C-002) and a nightly release (C-001)
#
# Terraform manages the AWS side (IAM role, scheduled actions). The controller itself is a Flux
# HelmRelease in k8s/infrastructure/cluster-autoscaler/, like the ALB controller.
# EKS managed node groups tag their Auto Scaling group for cluster-autoscaler auto-discovery.
# --------------------------------------------------------------------------------------------------

locals {
  worker_asg_name = module.eks.eks_managed_node_groups_autoscaling_group_names[0]
}

resource "aws_iam_policy" "cluster_autoscaler" {
  name        = "ClusterAutoscalerPolicy-${module.eks.cluster_name}"
  description = "Lets cluster-autoscaler resize this cluster's node groups only"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Discover"
        Effect = "Allow"
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup",
        ]
        Resource = "*"
      },
      {
        Sid    = "ResizeOwnGroups"
        Effect = "Allow"
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${module.eks.cluster_name}" = "owned"
          }
        }
      },
    ]
  })

  tags = local.common_tags
}

module "cluster_autoscaler_role" {
  source = "./modules/eks-pod-identity-role"

  role_name       = "ClusterAutoscalerRole-${module.eks.cluster_name}"
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "cluster-autoscaler"
  policy_arns     = [aws_iam_policy.cluster_autoscaler.arn]
  tags            = local.common_tags

  depends_on = [aws_eks_addon.eks_pod_identity_agent]
}

# Outside the usage window every worker is released; the control plane stays, so workloads return
# from cluster state when the window opens (within the accepted 30-minute startup delay).
# To work outside the window, raise the group by hand:
#   aws autoscaling update-auto-scaling-group --auto-scaling-group-name <name> \
#     --min-size 1 --desired-capacity 1
resource "aws_autoscaling_schedule" "workers_stop" {
  scheduled_action_name  = "release-workers"
  autoscaling_group_name = local.worker_asg_name
  recurrence             = var.usage_window_stop
  time_zone              = var.usage_window_time_zone
  min_size               = 0
  max_size               = 3
  desired_capacity       = 0
}

resource "aws_autoscaling_schedule" "workers_start" {
  scheduled_action_name  = "restore-workers"
  autoscaling_group_name = local.worker_asg_name
  recurrence             = var.usage_window_start
  time_zone              = var.usage_window_time_zone
  min_size               = 1
  max_size               = 3
  desired_capacity       = 1
}
