# GitHub Actions OIDC Provider and IAM Role
# This allows GitHub Actions to authenticate to AWS without long-lived credentials

data "aws_caller_identity" "current" {}

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

# OIDC Provider for Terraform Cloud
resource "aws_iam_openid_connect_provider" "terraform_cloud" {
  url = "https://app.terraform.io"

  client_id_list = [
    "aws.workload.identity",
  ]

  # Terraform Cloud OIDC thumbprint
  # This is the official thumbprint from HashiCorp documentation
  thumbprint_list = [
    "9e99a48a9960b14926bb7f3b02e22da2b0ab7280",
  ]

  tags = {
    Name        = "terraform-cloud-oidc"
    Environment = "permanent"
    ManagedBy   = "terraform"
    Purpose     = "Terraform Cloud OIDC authentication"
  }
}

# IAM Role for GitHub Actions and Terraform Cloud
resource "aws_iam_role" "github_actions" {
  name        = "GitHubActions-InfraFleet"
  description = "Role for GitHub Actions and Terraform Cloud to manage infrastructure"

  # Trust policy - allows both GitHub Actions and Terraform Cloud to assume this role
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
          }
          StringLike = {
            # Only allow this specific repository
            "token.actions.githubusercontent.com:sub" = "repo:your-org/infra-fleet:*"
          }
        }
      },
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.terraform_cloud.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "app.terraform.io:aud" = "aws.workload.identity"
          }
          StringLike = {
            # Allow this org across staging/permanent workspaces
            "app.terraform.io:sub" = [
              "organization:your-terraform-org:project:*:workspace:infra-fleet-staging:run_phase:*",
              "organization:your-terraform-org:project:*:workspace:infra-fleet-permanent:run_phase:*"
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

# IAM Policy with permissions needed for infrastructure automation
resource "aws_iam_policy" "github_actions" {
  name        = "GitHubActions-InfraFleet-Policy"
  description = "Permissions for GitHub Actions to manage EKS infrastructure"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:PassRole",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListRolePolicies",
          "iam:GetRolePolicy",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:GetPolicy",
          "iam:ListPolicyVersions",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:GetPolicyVersion",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:ListInstanceProfiles",
          "iam:ListInstanceProfilesForRole",
          "iam:TagRole",
          "iam:TagPolicy",
          "iam:TagInstanceProfile",
          "iam:CreateOpenIDConnectProvider",
          "iam:DeleteOpenIDConnectProvider",
          "iam:GetOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "autoscaling:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy",
          "logs:TagLogGroup",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagLogGroup",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:*",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:*"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:CreateKey",
          "kms:CreateAlias",
          "kms:DeleteAlias",
          "kms:DescribeKey",
          "kms:GetKeyPolicy",
          "kms:GetKeyRotationStatus",
          "kms:ListAliases",
          "kms:ListKeys",
          "kms:ListResourceTags",
          "kms:PutKeyPolicy",
          "kms:ScheduleKeyDeletion",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:EnableKeyRotation",
          "kms:DisableKey",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          "arn:aws:s3:::terraform-state-*",
          "arn:aws:s3:::terraform-state-*/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/terraform-state-lock*"
      },
      # STS (to get caller identity, useful for debugging)
      {
        Effect = "Allow"
        Action = [
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
    ]
  })

  tags = {
    Name        = "github-actions-policy"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "github_actions" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.github_actions.arn
}

# Outputs for use in GitHub Actions and Terraform Cloud workflows
output "github_actions_role_arn" {
  description = "ARN of the IAM role for GitHub Actions and Terraform Cloud to assume"
  value       = aws_iam_role.github_actions.arn
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider"
  value       = aws_iam_openid_connect_provider.github_actions.arn
}

output "terraform_cloud_oidc_provider_arn" {
  description = "ARN of the Terraform Cloud OIDC provider"
  value       = aws_iam_openid_connect_provider.terraform_cloud.arn
}
