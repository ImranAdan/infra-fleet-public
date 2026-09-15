# GitHub Actions OIDC Provider and IAM Role
# This allows GitHub Actions to authenticate to AWS without long-lived credentials

data "aws_caller_identity" "current" {}

locals {
  # This account operates in one region. Pinning regional statements to it
  # means a leaked GitHub Actions token cannot spin up resources elsewhere,
  # which is the usual first move after credential theft.
  eu_west_2_only = {
    StringEquals = {
      "aws:RequestedRegion" = "eu-west-2"
    }
  }
}

# OIDC Provider for GitHub Actions
resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com",
  ]

  # GitHub's OIDC thumbprint (verified from GitHub documentation)
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd", # Backup thumbprint
  ]

  tags = {
    Name        = "github-actions-oidc"
    Environment = "staging"
    ManagedBy   = "terraform"
    Purpose     = "GitHub Actions OIDC authentication"
  }
}

# IAM role for GitHub Actions. HCP Terraform stores state but each workspace
# uses Local execution, so it does not need an AWS identity of its own.
resource "aws_iam_role" "github_actions" {
  name        = "GitHubActions-InfraFleet"
  description = "Role for GitHub Actions to manage infrastructure"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            # GitHub changes the subject when a job uses an Environment, so
            # trust the deployment branch and the staging Environment exactly.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_repository}:ref:refs/heads/${var.github_deployment_branch}",
              "repo:${var.github_repository}:environment:${var.github_deployment_environment}",
            ]
          }
        }
      }
    ]
  })

  tags = {
    Name        = "github-actions-role"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}

# Permissions for GitHub Actions to manage infrastructure.
#
# Split across two managed policies purely because of the 6,144-character
# limit on a single managed policy - the enumerated statements below render
# to more than that as one document. The split is by service area, not by
# trust boundary: both are attached to the same role.
#
# Every statement is scoped by action, and by resource wherever the AWS API
# supports resource-level permissions. Regional statements are pinned to
# eu-west-2, the only region this account operates in.
#
# The one remaining action wildcard is "ec2:Describe*". EC2 Describe calls
# do not support resource-level permissions, are read-only, and the exact
# set the VPC and EKS modules invoke changes between provider releases.
# Enumerating them would add churn without narrowing blast radius.

# Policy 1: the cluster and the network it runs on.
resource "aws_iam_policy" "github_actions" {
  name        = "GitHubActions-InfraFleet-Policy"
  description = "EKS, EC2 and Auto Scaling permissions for the staging stack"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EKS: cluster, managed node groups, add-ons and access entries.
      {
        Sid    = "EksLifecycle"
        Effect = "Allow"
        Action = [
          "eks:AssociateAccessPolicy",
          "eks:CreateAccessEntry",
          "eks:CreateAddon",
          "eks:CreateCluster",
          "eks:CreateNodegroup",
          "eks:CreatePodIdentityAssociation",
          "eks:DeleteAccessEntry",
          "eks:DeleteAddon",
          "eks:DeleteCluster",
          "eks:DeleteNodegroup",
          "eks:DeletePodIdentityAssociation",
          "eks:DescribeAccessEntry",
          "eks:DescribeAddon",
          "eks:DescribeAddonConfiguration",
          "eks:DescribeAddonVersions",
          "eks:DescribeCluster",
          "eks:DescribeNodegroup",
          "eks:DescribePodIdentityAssociation",
          "eks:DescribeUpdate",
          "eks:DisassociateAccessPolicy",
          "eks:ListAccessEntries",
          "eks:ListAccessPolicies",
          "eks:ListAddons",
          "eks:ListAssociatedAccessPolicies",
          "eks:ListClusters",
          "eks:ListNodegroups",
          "eks:ListPodIdentityAssociations",
          "eks:ListTagsForResource",
          "eks:ListUpdates",
          "eks:TagResource",
          "eks:UntagResource",
          "eks:UpdateAccessEntry",
          "eks:UpdateAddon",
          "eks:UpdateClusterConfig",
          "eks:UpdateClusterVersion",
          "eks:UpdateNodegroupConfig",
          "eks:UpdateNodegroupVersion",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      # EC2 reads. No resource-level support; read-only by definition.
      {
        Sid    = "Ec2Read"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:GetSecurityGroupsForVpc",
        ]
        Resource = "*"
      },
      # EC2 writes: VPC, subnets, routing, NAT, security groups, and the
      # launch templates / instances behind EKS managed node groups.
      {
        Sid    = "Ec2Write"
        Effect = "Allow"
        Action = [
          "ec2:AllocateAddress",
          "ec2:AssociateAddress",
          "ec2:AssociateRouteTable",
          "ec2:AttachInternetGateway",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:CreateInternetGateway",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateLaunchTemplateVersion",
          "ec2:CreateNatGateway",
          "ec2:CreateNetworkAclEntry",
          "ec2:CreateNetworkInterface",
          "ec2:CreateRoute",
          "ec2:CreateRouteTable",
          "ec2:CreateSecurityGroup",
          "ec2:CreateSubnet",
          "ec2:CreateTags",
          "ec2:CreateVpc",
          "ec2:DeleteInternetGateway",
          "ec2:DeleteLaunchTemplate",
          "ec2:DeleteLaunchTemplateVersions",
          "ec2:DeleteNatGateway",
          "ec2:DeleteNetworkAclEntry",
          "ec2:DeleteNetworkInterface",
          "ec2:DeleteRoute",
          "ec2:DeleteRouteTable",
          "ec2:DeleteSecurityGroup",
          "ec2:DeleteSubnet",
          "ec2:DeleteTags",
          "ec2:DeleteVolume",
          "ec2:DeleteVpc",
          "ec2:DetachInternetGateway",
          "ec2:DetachNetworkInterface",
          "ec2:DisassociateAddress",
          "ec2:DisassociateRouteTable",
          "ec2:ModifyLaunchTemplate",
          "ec2:ModifyNetworkInterfaceAttribute",
          "ec2:ModifySecurityGroupRules",
          "ec2:ModifySubnetAttribute",
          "ec2:ModifyVpcAttribute",
          "ec2:ReleaseAddress",
          "ec2:ReplaceNetworkAclEntry",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RunInstances",
          "ec2:TerminateInstances",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      # Auto Scaling groups backing the EKS managed node group.
      {
        Sid    = "AutoScaling"
        Effect = "Allow"
        Action = [
          "autoscaling:CreateAutoScalingGroup",
          "autoscaling:CreateOrUpdateTags",
          "autoscaling:DeleteAutoScalingGroup",
          "autoscaling:DeleteTags",
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeInstanceRefreshes",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "autoscaling:SetDesiredCapacity",
          "autoscaling:StartInstanceRefresh",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
          "autoscaling:UpdateAutoScalingGroup",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      # IAM: cluster, node group and IRSA roles. Global service - no region
      # condition applies.
      #
      # This statement must stay in THIS policy - the one that already exists
      # and is already attached. The permanent stack is applied by the very
      # role it manages. If these permissions lived in the second policy,
      # Terraform could narrow this one before the second was created and
      # attached, leaving the role without iam:CreatePolicy or
      # iam:AttachRolePolicy and unable to finish, or repair, its own apply.
      {
        Sid    = "Iam"
        Effect = "Allow"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:AttachRolePolicy",
          "iam:CreateInstanceProfile",
          "iam:CreateOpenIDConnectProvider",
          "iam:CreatePolicy",
          "iam:CreatePolicyVersion",
          "iam:CreateRole",
          "iam:DeleteInstanceProfile",
          "iam:DeleteOpenIDConnectProvider",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:DeleteRole",
          "iam:DeleteRolePolicy",
          "iam:DetachRolePolicy",
          "iam:GetInstanceProfile",
          "iam:GetOpenIDConnectProvider",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfiles",
          "iam:ListInstanceProfilesForRole",
          "iam:ListPolicyVersions",
          "iam:ListRolePolicies",
          "iam:PutRolePolicy",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:TagOpenIDConnectProvider",
          "iam:TagPolicy",
          "iam:TagRole",
          "iam:UntagOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
        ]
        # Scoped to this account's own IAM namespace. The role has no reason to
        # write IAM in any other account, and a cross-account ARN reaching this
        # statement would be a bug or an attack, never a normal apply.
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/*",
        ]
      },
      # Explicit Deny closing the one-step escalation: attaching an AWS-managed
      # administrator policy to a role this principal can already assume.
      #
      # A Deny always beats the Allow above, and none of these policies appear
      # anywhere in this repository - the stacks attach only the EKS, CNI and
      # ECR service policies - so this cannot affect a legitimate apply.
      #
      # This is a partial control, not the complete one. iam:PutRolePolicy still
      # permits an inline policy granting "Action": "*", and IAM conditions
      # cannot inspect a policy document. Closing that requires a permissions
      # boundary: a boundary policy in this stack, an iam:PermissionsBoundary
      # condition on CreateRole/PutRolePolicy/AttachRolePolicy, and every
      # role-creating call - including the EKS module's
      # iam_role_permissions_boundary and node_iam_role_permissions_boundary -
      # attaching it. That change denies CreateRole until every caller sets the
      # boundary, so it needs a full plan, apply and destroy cycle to validate
      # before it can be merged. Tracked in docs/SECURITY-CONCERNS.md (H5).
      {
        Sid    = "DenyAdministratorPolicyAttachment"
        Effect = "Deny"
        Action = [
          "iam:AttachRolePolicy",
          "iam:AttachUserPolicy",
          "iam:AttachGroupPolicy",
        ]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "iam:PolicyARN" = [
              "arn:aws:iam::aws:policy/AdministratorAccess",
              "arn:aws:iam::aws:policy/IAMFullAccess",
              "arn:aws:iam::aws:policy/PowerUserAccess",
            ]
          }
        }
      },
      # Once a permissions boundary exists, nothing in CI should be able to
      # remove it from a role. Denying that now means the boundary work above
      # cannot be quietly undone later by a policy edit.
      {
        Sid      = "DenyPermissionsBoundaryRemoval"
        Effect   = "Deny"
        Action   = "iam:DeleteRolePermissionsBoundary"
        Resource = "*"
      },
      # iam:PassRole is separated so it can carry a condition. Without one it
      # is the strongest privilege in this role: an assumed principal could
      # hand any existing role to any service. Constrained to the services
      # this stack actually provisions - EKS control plane, EKS managed node
      # groups, and the EC2 instances behind them.
      #
      # If an apply fails with AccessDenied on iam:PassRole, add the service
      # principal named in the error here. Do not remove the condition.
      {
        Sid      = "IamPassRoleToStackServices"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "*"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "ec2.amazonaws.com",
              "eks-nodegroup.amazonaws.com",
              "eks.amazonaws.com",
            ]
          }
        }
      },
    ]
  })

  tags = {
    Name        = "github-actions-policy"
    Environment = "staging"
    ManagedBy   = "terraform"
  }

  # Narrowing this policy must not happen before the supporting policy is
  # attached. The permanent stack is applied by the role it manages, and
  # Terraform treats the in-place update here and the creation of the second
  # policy as independent - either order is valid to it. If this narrowed
  # first, the role would lose SSM, ECR, CloudWatch Logs and KMS before
  # regaining them, and any remaining call in the same apply - the ECR
  # repository in this stack, for instance - would fail with AccessDenied
  # partway through.
  #
  # The IAM statements above are kept in this policy for the same reason,
  # belt and braces: ordering fixes this apply, keeping the permissions here
  # means no ordering can take away the role's ability to repair itself.
  depends_on = [aws_iam_role_policy_attachment.github_actions_supporting]
}

# Policy 2: the supporting services the stack depends on.
resource "aws_iam_policy" "github_actions_supporting" {
  name        = "GitHubActions-InfraFleet-Supporting-Policy"
  description = "Logging, SSM, ECR, KMS and load balancer cleanup permissions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EKS control plane log groups.
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:ListTagsForResource",
          "logs:PutRetentionPolicy",
          "logs:TagLogGroup",
          "logs:TagResource",
          "logs:UntagLogGroup",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      # SSM is used for one thing only: resolving EKS-optimised AMI IDs from
      # AWS-published public parameters. Scoped to those paths.
      {
        Sid    = "SsmPublicAmiParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
        ]
        Resource = [
          "arn:aws:ssm:eu-west-2::parameter/aws/service/ami-amazon-linux-latest/*",
          "arn:aws:ssm:eu-west-2::parameter/aws/service/bottlerocket/*",
          "arn:aws:ssm:eu-west-2::parameter/aws/service/eks/*",
        ]
      },
      # ECR: registry-wide token, then everything else scoped to repositories
      # in this account and region.
      {
        Sid       = "EcrAuthToken"
        Effect    = "Allow"
        Action    = "ecr:GetAuthorizationToken"
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      {
        Sid    = "EcrRepositories"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchDeleteImage",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:CreateRepository",
          "ecr:DeleteLifecyclePolicy",
          "ecr:DeleteRepository",
          "ecr:DeleteRepositoryPolicy",
          "ecr:DescribeImages",
          "ecr:DescribeRepositories",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetLifecyclePolicy",
          "ecr:GetRepositoryPolicy",
          "ecr:InitiateLayerUpload",
          "ecr:ListImages",
          "ecr:ListTagsForResource",
          "ecr:PutImage",
          "ecr:PutImageScanningConfiguration",
          "ecr:PutImageTagMutability",
          "ecr:PutLifecyclePolicy",
          "ecr:SetRepositoryPolicy",
          "ecr:TagResource",
          "ecr:UntagResource",
          "ecr:UploadLayerPart",
        ]
        Resource = "arn:aws:ecr:eu-west-2:${data.aws_caller_identity.current.account_id}:repository/*"
      },
      # Load balancers created in-cluster by the AWS Load Balancer Controller
      # outlive the cluster, so scripts/cleanup-k8s-resources-v2.sh deletes
      # them before Terraform destroy runs. The previous policy had no
      # elasticloadbalancing permissions at all, so that cleanup could never
      # have worked; adding it here rather than leaving a known gap.
      {
        Sid    = "LoadBalancerCleanup"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeTags",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      {
        Sid    = "Kms"
        Effect = "Allow"
        Action = [
          "kms:CreateAlias",
          "kms:CreateKey",
          "kms:DeleteAlias",
          "kms:DescribeKey",
          "kms:DisableKey",
          "kms:EnableKeyRotation",
          "kms:GetKeyPolicy",
          "kms:GetKeyRotationStatus",
          "kms:ListAliases",
          "kms:ListKeys",
          "kms:ListResourceTags",
          "kms:PutKeyPolicy",
          "kms:ScheduleKeyDeletion",
          "kms:TagResource",
          "kms:UntagResource",
        ]
        Resource  = "*"
        Condition = local.eu_west_2_only
      },
      {
        Sid      = "StsIdentity"
        Effect   = "Allow"
        Action   = "sts:GetCallerIdentity"
        Resource = "*"
      },
    ]
  })

  tags = {
    Name        = "github-actions-supporting-policy"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "github_actions" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions.arn
}

resource "aws_iam_role_policy_attachment" "github_actions_supporting" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions_supporting.arn
}

# Outputs for use in GitHub Actions and local bootstrap
output "github_actions_role_arn" {
  description = "ARN of the IAM role for GitHub Actions to assume"
  value       = aws_iam_role.github_actions.arn
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider"
  value       = aws_iam_openid_connect_provider.github_actions.arn
}
