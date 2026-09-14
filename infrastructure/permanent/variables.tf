variable "github_repository" {
  description = "GitHub repository allowed to assume the automation role, in OWNER/REPOSITORY form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use OWNER/REPOSITORY form."
  }
}

variable "github_deployment_branch" {
  description = "Branch allowed to assume the automation role outside a GitHub Environment."
  type        = string
  default     = "main"

  validation {
    condition     = length(trimspace(var.github_deployment_branch)) > 0
    error_message = "github_deployment_branch must not be empty."
  }
}

variable "github_deployment_environment" {
  description = "GitHub Environment allowed to assume the automation role for staging deployments."
  type        = string
  default     = "staging"

  validation {
    condition     = length(trimspace(var.github_deployment_environment)) > 0
    error_message = "github_deployment_environment must not be empty."
  }
}
