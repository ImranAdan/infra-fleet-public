terraform {
  # Require Terraform 1.14.x or higher (but less than 2.0)
  # This prevents version mismatch issues between local and Terraform Cloud
  # Matches TFC workspace requirement: ~> 1.14.0
  required_version = ">= 1.14.0, < 2.0.0"

  # Terraform Cloud backend configuration
  # State is stored remotely. The workspace uses Local execution so AWS calls
  # run on the GitHub runner after it assumes the repository's OIDC role.
  cloud {
    # organization and workspace come from TF_CLOUD_ORGANIZATION and
    # TF_WORKSPACE, set by .github/actions/setup-aws-terraform.
    #
    # They cannot be Terraform variables - the cloud block is parsed before
    # variables exist - so environment variables are the only supported way to
    # externalise them. This keeps one organisation's name out of a public
    # template and lets an adopter point the stack at their own HCP Terraform
    # organisation without editing any .tf file.
    #
    # See CONFIGURATION.md.
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.15.0, < 7.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.1"
    }
    # Note: Flux-related providers (flux, kubernetes, kubectl, github, tls) have been removed.
    # Flux is now bootstrapped outside of Terraform via the rebuild-stack.yml workflow.
    # See flux.tf for details.
  }
}

provider "aws" {
  region = local.aws_region
}
