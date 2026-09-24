#!/usr/bin/env bash

set -euo pipefail

repository_root=$(git rev-parse --show-toplevel)
mode="${1:-plan}"
# shellcheck source=scripts/aws-profile-config.sh
source "$repository_root/scripts/aws-profile-config.sh"

if [ "$mode" != "plan" ] && [ "$mode" != "--apply" ]; then
  echo "Usage: $0 [plan|--apply]" >&2
  exit 2
fi

aws_profile_load_config "$repository_root"

for command_name in aws terraform; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

export TF_WORKSPACE="$TF_WORKSPACE_PERMANENT"
export TF_VAR_github_repository="$GITHUB_REPOSITORY"
export TF_VAR_github_deployment_branch="$GITHUB_DEPLOYMENT_BRANCH"
export TF_VAR_github_deployment_environment="$GITHUB_DEPLOYMENT_ENVIRONMENT"
export TF_VAR_cost_owner="${COST_OWNER:-infra-fleet}"

echo "Checking the local AWS identity used for bootstrap..."
identity_arn=$(aws sts get-caller-identity --query Arn --output text)
aws_account_id=$(aws sts get-caller-identity --query Account --output text)
echo "$identity_arn"

terraform -chdir="$repository_root/infrastructure/permanent" fmt -check
terraform -chdir="$repository_root/infrastructure/permanent" init -input=false
terraform -chdir="$repository_root/infrastructure/permanent" validate

github_oidc_provider_arn="arn:aws:iam::${aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
provider_exists=$(aws iam list-open-id-connect-providers \
  --query "contains(OpenIDConnectProviderList[].Arn, '${github_oidc_provider_arn}')" \
  --output text)

if [ "$provider_exists" = "True" ]; then
  state_resources=$(terraform -chdir="$repository_root/infrastructure/permanent" state list)
  if ! grep -qx 'aws_iam_openid_connect_provider.github_actions' <<< "$state_resources"; then
    echo "GitHub's account-wide OIDC provider already exists but is not in this workspace." >&2
    echo "Import it, review the next plan, then rerun this script:" >&2
    echo "terraform -chdir=infrastructure/permanent import aws_iam_openid_connect_provider.github_actions $github_oidc_provider_arn" >&2
    exit 1
  fi
fi

if [ "$mode" = "--apply" ]; then
  echo "Applying the permanent stack from this machine..."
  terraform -chdir="$repository_root/infrastructure/permanent" apply
  terraform -chdir="$repository_root/infrastructure/permanent" output github_actions_role_arn
else
  echo "Creating a permanent-stack plan. Pass --apply only after reviewing it."
  terraform -chdir="$repository_root/infrastructure/permanent" plan -input=false
fi
