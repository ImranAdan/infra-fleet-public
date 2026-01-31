terraform {
  # Require Terraform 1.14.x or higher (but less than 2.0)
  # This prevents version mismatch issues between local and Terraform Cloud
  # Matches TFC workspace requirement: ~> 1.14.0
  required_version = ">= 1.14.0, < 2.0.0"

  # Terraform Cloud backend configuration
  # State is stored remotely and runs can execute on Terraform Cloud infrastructure
  cloud {
    organization = "your-terraform-org"

    workspaces {
      name = "infra-fleet-staging"
    }
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
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
    # Note: Flux-related providers (flux, kubernetes, kubectl, github, tls) have been removed.
    # Flux is now bootstrapped outside of Terraform via the rebuild-stack.yml workflow.
    # See flux.tf for details.
  }
}

provider "aws" {
  region = local.aws_region
}
