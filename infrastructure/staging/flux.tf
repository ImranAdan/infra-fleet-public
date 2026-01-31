# --------------------------------------------------------------------------------------------------
# Flux GitOps Bootstrap
#
# IMPORTANT: Flux is now bootstrapped OUTSIDE of Terraform via the rebuild-stack.yml workflow.
#
# This architectural change was made because:
# 1. The Flux provider requires a live EKS cluster to initialize
# 2. When the cluster is down (after nightly destroy), terraform plan/apply would fail
# 3. Moving Flux to the rebuild workflow eliminates provider initialization issues
# 4. This matches Flux's GitOps philosophy - its state belongs in Git, not Terraform
#
# Flux bootstrap is now handled by:
#   - .github/workflows/rebuild-stack.yml (flux bootstrap github command)
#   - k8s/flux-system/ (manifests managed by Flux itself)
#
# The terraform-outputs ConfigMap for Flux variable substitution is also created
# in the rebuild workflow via kubectl.
#
# See: docs/GITOPS-SETUP.md for architecture and setup details
# --------------------------------------------------------------------------------------------------
