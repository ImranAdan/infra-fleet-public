variable "automation_role_name" {
  description = "Name of the permanent-stack IAM role used by GitHub Actions."
  type        = string
  default     = "GitHubActions-InfraFleet"

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", var.automation_role_name))
    error_message = "automation_role_name must be a valid IAM role name."
  }
}

variable "eks_admin_principal_arns" {
  description = "Additional IAM user or role ARNs granted EKS cluster-admin access. Empty by default."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.eks_admin_principal_arns :
      can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:(role|user)/.+$", arn))
    ])
    error_message = "Each EKS admin principal must be an IAM role or user ARN."
  }
}
