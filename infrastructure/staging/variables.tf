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

variable "cost_owner" {
  description = "Owner cost-allocation tag applied to every taggable AWS resource by default."
  type        = string
  default     = "infra-fleet"
}

# The owner-defined usage window for staging workers (intent C-001).
variable "usage_window_start" {
  description = "Cron recurrence that restores staging workers"
  type        = string
  default     = "0 8 * * MON-FRI"
}

variable "usage_window_stop" {
  description = "Cron recurrence that releases every staging worker"
  type        = string
  default     = "0 20 * * MON-FRI"
}

variable "usage_window_time_zone" {
  description = "IANA time zone for the usage window"
  type        = string
  default     = "Europe/London"
}
