# --------------------------------------------------------------------------------------------------
# Cloudflare DNS Configuration
# Manages DNS records for example.com domain
# --------------------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------------------
# Provider Configuration
# --------------------------------------------------------------------------------------------------
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# --------------------------------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------------------------------
variable "cloudflare_api_token" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Cloudflare API token with Zone:DNS:Edit permissions for example.com. Optional - DNS is managed by rebuild-stack workflow, not Terraform."
}

variable "cloudflare_zone_id" {
  type        = string
  default     = ""
  description = "Cloudflare Zone ID for example.com. Optional - DNS is managed by rebuild-stack workflow, not Terraform."
}

variable "app_subdomain" {
  type        = string
  default     = "app"
  description = "Subdomain for the application (e.g., app.example.com)"
}

variable "domain_name" {
  type        = string
  default     = "example.com"
  description = "Root domain name"
}

# --------------------------------------------------------------------------------------------------
# DNS Record
# Note: The actual CNAME content (NLB hostname) is managed by the rebuild-stack workflow
# after the NLB is provisioned. This resource creates the initial record.
# --------------------------------------------------------------------------------------------------
# DNS record is created/updated by the workflow after NLB is provisioned
# Terraform only manages the provider configuration here

# --------------------------------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------------------------------
output "app_hostname" {
  value       = "${var.app_subdomain}.${var.domain_name}"
  description = "Full hostname for the application"
}
