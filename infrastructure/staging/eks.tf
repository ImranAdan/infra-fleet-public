module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.15.1"

  name               = local.cluster_name
  kubernetes_version = "1.32"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Hybrid access configuration:
  # - Public access enabled for Terraform Cloud workers and GitHub Actions
  # - Private access enabled for in-VPC resources
  #
  # Open to all IPs (0.0.0.0/0) because:
  # - Terraform Cloud workers use dynamic, ephemeral IPs that cannot be whitelisted
  # - IAM authentication is required (no anonymous access)
  # - Stack is ephemeral (~8-10 hours/day, nightly destroy at 8 PM UTC)
  #
  # See: docs/terraform-cloud-eks-ddr.md for full decision rationale
  # Security: Trivy findings AVD-AWS-0040/AVD-AWS-0041 documented in .trivyignore
  endpoint_public_access       = true
  endpoint_private_access      = true
  endpoint_public_access_cidrs = ["0.0.0.0/0"]

  create_kms_key    = false
  encryption_config = null

  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.large"] # Upgraded from t3.medium: 35 pods vs 17, 8GB RAM vs 4GB (required for HPA scaling)
      capacity_type  = "SPOT"       # Use spot instances for ~70% cost savings (acceptable for dev/staging)
      desired_size   = 1
      min_size       = 1
      max_size       = 2

      # Enforce IMDSv2 for enhanced metadata security
      # https://avd.aquasec.com/misconfig/aws-autoscaling-enforce-http-token-imds
      metadata_options = {
        http_endpoint               = "enabled"
        http_tokens                 = "required" # Requires IMDSv2 token for metadata access
        http_put_response_hop_limit = 1          # Limit to prevent SSRF attacks
      }
    }
  }

  # Specifies the authentication mode. "API_AND_CONFIG_MAP" allows both EKS Access Entries and the
  # aws-auth ConfigMap to be used for authentication.
  authentication_mode = "API_AND_CONFIG_MAP"

  # Creates EKS Access Entries to grant IAM roles administrative privileges to the cluster
  access_entries = {
    # Session Manager jumpbox access - DISABLED (see session-manager.tf.disabled)
    # Uncomment when needed (will incur ~$10-15/month EC2 cost)
    # session_manager = {
    #   principal_arn = aws_iam_role.session_manager_role.arn
    #
    #   policy_associations = {
    #     admin = {
    #       policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
    #       access_scope = {
    #         type = "cluster"
    #       }
    #     }
    #   }
    # }

    # GitHub Actions / Terraform Cloud OIDC role access
    github_actions = {
      principal_arn = "arn:aws:iam::${local.aws_account_id}:role/GitHubActions-InfraFleet"

      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }

    # Local developer IAM user access
    #
    # Enables local kubectl access for development and debugging.
    # Acceptable for ephemeral dev/staging stack with nightly destroy.
    #
    # For production, consider: AWS SSO, OIDC federation, or breakglass role
    local_developer = {
      principal_arn = "arn:aws:iam::${local.aws_account_id}:user/imran"

      policy_associations = {
        admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = {
            type = "cluster"
          }
        }
      }
    }
  }

  # Security group rules - DISABLED (session manager commented out)
  # Uncomment when session manager is re-enabled
  # security_group_additional_rules = {
  #   allow_jumpbox_https = {
  #     cidr_blocks               = [module.vpc.vpc_cidr_block]
  #     description               = "Allow HTTPS from Session Manager jumpbox"
  #     protocol                  = "tcp"
  #     from_port                 = 443
  #     to_port                   = 443
  #     type                      = "ingress"
  #     source_security_group_ids = [aws_security_group.session_manager_sg.id]
  #   }
  # }

  # Add-ons will be defined as separate resources for better control

  tags = local.common_tags
}

# --------------------------------------------------------------------------------------------------
# EKS Add-ons - Staged Dependencies
# Critical add-ons (VPC CNI, kube-proxy) are created immediately for node health.
# Non-critical add-ons (CoreDNS, Pod Identity) depend on the node group being ready.
# --------------------------------------------------------------------------------------------------

# Stage 1: Critical add-ons for node health (no dependencies)
# VPC CNI - Critical for pod networking and node Ready status
resource "aws_eks_addon" "vpc_cni" {
  cluster_name = module.eks.cluster_name
  addon_name   = "vpc-cni"
}

# kube-proxy - Critical for network rules and node communication
resource "aws_eks_addon" "kube_proxy" {
  cluster_name = module.eks.cluster_name
  addon_name   = "kube-proxy"
}

# Stage 2: Non-critical add-ons (depend on node group completion)
# CoreDNS - DNS resolution (only needed after nodes are Ready)
resource "aws_eks_addon" "coredns" {
  cluster_name = module.eks.cluster_name
  addon_name   = "coredns"

  # Single replica to optimize pod capacity on t3.large (35 pod limit)
  # Default is 2 replicas - acceptable to reduce for non-production ephemeral stack
  configuration_values = jsonencode({
    replicaCount = 1
  })

  # Wait for node group to be ready before creating CoreDNS
  depends_on = [module.eks]
}

# EKS Pod Identity Agent - Modern IAM integration (non-critical)
resource "aws_eks_addon" "eks_pod_identity_agent" {
  cluster_name = module.eks.cluster_name
  addon_name   = "eks-pod-identity-agent"

  # Wait for node group to be ready
  depends_on = [module.eks]
}

# Metrics Server - Required for HPA (Horizontal Pod Autoscaler)
# Collects CPU/memory metrics from kubelets and exposes via Metrics API
# Enables: kubectl top nodes/pods, HPA scaling decisions
# See: https://github.com/your-org/infra-fleet/issues/148
resource "aws_eks_addon" "metrics_server" {
  cluster_name = module.eks.cluster_name
  addon_name   = "metrics-server"

  # Single replica to optimize pod capacity on t3.large (35 pod limit)
  # Default is 2 replicas - acceptable to reduce for non-production ephemeral stack
  configuration_values = jsonencode({
    replicas = 1
  })

  # Wait for node group to be ready
  depends_on = [module.eks]
}

output "cluster_name" {
  description = "The name of the EKS cluster."
  value       = module.eks.cluster_name
}
