#!/usr/bin/env bash

set -euo pipefail

repository_root=$(git rev-parse --show-toplevel)
# shellcheck source=scripts/aws-profile-config.sh
source "$repository_root/scripts/aws-profile-config.sh"

mode=${1:-plan}
if [ "$mode" != plan ] && [ "$mode" != --apply ]; then
  echo "Usage: $0 [plan|--apply]" >&2
  exit 2
fi

aws_profile_load_config "$repository_root"

for command_name in aws terraform gh; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 1
  fi
done

echo "AWS target: $(aws sts get-caller-identity --query Arn --output text)"
echo "GitHub target: $GITHUB_REPOSITORY (branch main, environment staging)"
echo "HCP Terraform target: $TF_CLOUD_ORGANIZATION/$TF_WORKSPACE_PERMANENT and $TF_WORKSPACE_STAGING"

gh auth status >/dev/null
actual_repository=$(gh repo view "$GITHUB_REPOSITORY" --json nameWithOwner --jq .nameWithOwner)
if [ "$actual_repository" != "$GITHUB_REPOSITORY" ]; then
  echo "GitHub CLI resolved $actual_repository instead of $GITHUB_REPOSITORY." >&2
  exit 1
fi

read_credential() {
  local name=$1 prompt=$2 value=${!1:-}
  if [ -z "$value" ]; then
    if [ ! -t 0 ]; then
      echo "$name must be exported for non-interactive AWS setup." >&2
      return 1
    fi
    read -r -s -p "$prompt: " value
    echo >&2
  fi
  if [ -z "$value" ]; then
    echo "$name must not be empty." >&2
    return 1
  fi
  printf -v "$name" '%s' "$value"
}

if [ "$mode" = --apply ]; then
  # Collect every required value before the first mutation. Values are sent to
  # GitHub over stdin and never placed in command arguments or config.env.
  read_credential TF_API_TOKEN 'HCP Terraform API token'
  read_credential FLUX_GITHUB_TOKEN 'Fine-grained GitHub token for Flux'
  read_credential GRAFANA_ADMIN_PASSWORD 'Grafana administrator password'
  export -n TF_API_TOKEN FLUX_GITHUB_TOKEN GRAFANA_ADMIN_PASSWORD
  export TF_TOKEN_app_terraform_io=$TF_API_TOKEN
fi

if { [ -n "${APP_HOSTNAME:-}" ] && [ -z "${ACME_EMAIL:-}" ]; } ||
  { [ -z "${APP_HOSTNAME:-}" ] && [ -n "${ACME_EMAIL:-}" ]; }; then
  echo 'APP_HOSTNAME and ACME_EMAIL must be supplied together.' >&2
  exit 1
fi
if [ -n "${APP_HOSTNAME:-}" ] &&
  [[ ! "$APP_HOSTNAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo 'APP_HOSTNAME is not a valid DNS hostname.' >&2
  exit 1
fi
if [ -n "${ACME_EMAIL:-}" ] &&
  [[ ! "$ACME_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then
  echo 'ACME_EMAIL is not a valid email address.' >&2
  exit 1
fi
if { [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -z "${CLOUDFLARE_ZONE_ID:-}" ]; } ||
  { [ -z "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ZONE_ID:-}" ]; }; then
  echo 'CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID must be supplied together.' >&2
  exit 1
fi
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -z "${APP_HOSTNAME:-}" ]; then
  echo 'Cloudflare automation also requires APP_HOSTNAME and ACME_EMAIL.' >&2
  exit 1
fi
export -n LOAD_HARNESS_API_KEY CLOUDFLARE_API_TOKEN CLOUDFLARE_ZONE_ID 2>/dev/null || true

environment_api="repos/$GITHUB_REPOSITORY/environments/$GITHUB_DEPLOYMENT_ENVIRONMENT"
branch_policy_api="$environment_api/deployment-branch-policies"
gh_error=$(mktemp)
trap 'rm -f "$gh_error"' EXIT

# Only a confirmed 404 means the Environment is absent. Any other failure stops
# setup, because creating over an unreadable Environment would reset its
# reviewers and wait timer.
environment_exists=false
if custom_policies=$(gh api "$environment_api" \
  --jq '.deployment_branch_policy.custom_branch_policies // false' 2>"$gh_error"); then
  environment_exists=true
  if [ "$custom_policies" != true ]; then
    echo "Existing GitHub Environment $GITHUB_DEPLOYMENT_ENVIRONMENT does not use custom branch policies." >&2
    echo 'Review its protection rules manually; setup will not replace them.' >&2
    exit 1
  fi
elif ! grep -q 'HTTP 404' "$gh_error"; then
  echo "Could not read GitHub Environment $GITHUB_DEPLOYMENT_ENVIRONMENT:" >&2
  cat "$gh_error" >&2
  exit 1
fi

# The OIDC role trusts the Environment subject, not a branch, so the
# Environment's deployment policies are the ref boundary. Accept exactly the
# main branch and v* tags; anything broader or mistyped is left to an
# administrator rather than silently widened or masked.
existing_policies=
if [ "$environment_exists" = true ]; then
  existing_policies=$(gh api "$branch_policy_api" \
    --paginate --jq '.branch_policies[] | "\(.type // "branch") \(.name)"')
  unexpected_policies=$(grep -Fvx -e 'branch main' -e 'tag v*' <<< "$existing_policies" || true)
  if [ -n "$unexpected_policies" ]; then
    echo "GitHub Environment $GITHUB_DEPLOYMENT_ENVIRONMENT admits refs other than branch main and tag v*:" >&2
    echo "$unexpected_policies" >&2
    echo 'Remove them manually; setup will not replace them.' >&2
    exit 1
  fi
fi

ensure_policy() {
  local name=$1 type=$2
  if ! grep -Fqx "$type $name" <<< "$existing_policies"; then
    gh api --method POST "$branch_policy_api" \
      -f "name=$name" -f "type=$type" >/dev/null
  fi
}

if [ "$mode" = --apply ]; then
  # Establish the reversible GitHub boundary before the permanent AWS apply.
  # If the session cannot administer the target repository, fail before any
  # cloud resource can be created.
  if [ "$environment_exists" = false ]; then
    gh api --method PUT "$environment_api" --input - >/dev/null <<'JSON'
{
  "wait_timer": 0,
  "prevent_self_review": false,
  "deployment_branch_policy": {
    "protected_branches": false,
    "custom_branch_policies": true
  }
}
JSON
  fi
  ensure_policy main branch
  ensure_policy 'v*' tag
fi

validate_staging_workspace() {
  echo "Validating the HCP Terraform staging workspace..."
  TF_WORKSPACE=$TF_WORKSPACE_STAGING \
    terraform -chdir="$repository_root/infrastructure/staging" init -input=false
  TF_WORKSPACE=$TF_WORKSPACE_STAGING \
    terraform -chdir="$repository_root/infrastructure/staging" validate
}

validate_staging_workspace

if [ "$mode" = plan ]; then
  "$repository_root/scripts/bootstrap-permanent.sh" plan
  echo "Next: ./fleet setup --profile aws-staging --apply"
  exit 0
fi

"$repository_root/scripts/bootstrap-permanent.sh" --apply
role_arn=$(TF_WORKSPACE=$TF_WORKSPACE_PERMANENT \
  terraform -chdir="$repository_root/infrastructure/permanent" output -raw github_actions_role_arn)
if [[ ! "$role_arn" =~ ^arn:aws:iam::[0-9]{12}:role/.+ ]]; then
  echo 'Permanent bootstrap returned an invalid GitHub Actions role ARN.' >&2
  exit 1
fi
unset TF_TOKEN_app_terraform_io

set_secret() {
  local name=$1 value=${!1}
  printf '%s' "$value" | gh secret set "$name" --repo "$GITHUB_REPOSITORY"
}

set_variable() {
  local name=$1 value=$2
  gh variable set "$name" --body "$value" --repo "$GITHUB_REPOSITORY"
}

AWS_GITHUB_ACTIONS_ROLE_ARN=$role_arn
export AWS_GITHUB_ACTIONS_ROLE_ARN
set_secret AWS_GITHUB_ACTIONS_ROLE_ARN
set_secret TF_API_TOKEN
set_secret TF_CLOUD_ORGANIZATION
set_secret FLUX_GITHUB_TOKEN
set_secret GRAFANA_ADMIN_PASSWORD

set_variable TF_WORKSPACE_PERMANENT "$TF_WORKSPACE_PERMANENT"
set_variable TF_WORKSPACE_STAGING "$TF_WORKSPACE_STAGING"
set_variable EKS_ADMIN_PRINCIPAL_ARNS_JSON "${EKS_ADMIN_PRINCIPAL_ARNS_JSON:-[]}"
set_variable COST_OWNER "${COST_OWNER:-infra-fleet}"

# Optional settings are reconciled, not only added: config.env is the source of
# truth, so a value removed from it is removed from the repository too. Without
# this, a retained APP_HOSTNAME would keep a public TLS/DNS path alive.
existing_secrets=$(gh secret list --repo "$GITHUB_REPOSITORY" --json name --jq '.[].name')
existing_variables=$(gh variable list --repo "$GITHUB_REPOSITORY" --json name --jq '.[].name')
for optional_secret in \
  LOAD_HARNESS_API_KEY \
  CLOUDFLARE_API_TOKEN \
  CLOUDFLARE_ZONE_ID; do
  if [ -n "${!optional_secret:-}" ]; then
    set_secret "$optional_secret"
  elif grep -Fqx "$optional_secret" <<< "$existing_secrets"; then
    gh secret delete "$optional_secret" --repo "$GITHUB_REPOSITORY"
  fi
done
for optional_variable in APP_HOSTNAME ACME_EMAIL; do
  if [ -n "${!optional_variable:-}" ]; then
    set_variable "$optional_variable" "${!optional_variable}"
  elif grep -Fqx "$optional_variable" <<< "$existing_variables"; then
    gh variable delete "$optional_variable" --repo "$GITHUB_REPOSITORY"
  fi
done

echo "AWS staging onboarding is configured for $GITHUB_REPOSITORY."
echo 'Next: ./fleet up --profile aws-staging'
