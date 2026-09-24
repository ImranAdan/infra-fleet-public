#!/usr/bin/env bash
# AWS onboarding contract without network, GitHub or cloud mutations.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin"

cat > "$scratch/config.env" <<'EOF'
GITHUB_REPOSITORY=example/fleet
GITHUB_DEPLOYMENT_BRANCH=main
GITHUB_DEPLOYMENT_ENVIRONMENT=staging
TF_CLOUD_ORGANIZATION=example
TF_WORKSPACE_PERMANENT=infra-fleet-permanent
TF_WORKSPACE_STAGING=infra-fleet-staging
EKS_ADMIN_PRINCIPAL_ARNS_JSON='[]'
EOF

cat > "$scratch/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'aws %s\n' "$*" >> "$FLEET_TEST_CALLS"
case "$*" in
  'sts get-caller-identity --query Arn --output text')
    echo 'arn:aws:iam::123456789012:user/operator' ;;
  'sts get-caller-identity --query Account --output text')
    echo '123456789012' ;;
  'iam list-open-id-connect-providers '* )
    echo 'False' ;;
esac
EOF

cat > "$scratch/bin/terraform" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'terraform %s\n' "$*" >> "$FLEET_TEST_CALLS"
case "$*" in
  *' output -raw github_actions_role_arn')
    echo 'arn:aws:iam::123456789012:role/GitHubActions-InfraFleet' ;;
esac
EOF

cat > "$scratch/bin/gh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  'auth status')
    printf 'gh auth status\n' >> "$FLEET_TEST_CALLS" ;;
  'repo view')
    printf 'gh repo view %s\n' "$2" >> "$FLEET_TEST_CALLS"
    echo "$GITHUB_REPOSITORY" ;;
  'secret set')
    value=$(cat)
    printf 'gh secret %s bytes=%s\n' "$3" "${#value}" >> "$FLEET_TEST_CALLS" ;;
  'variable set')
    printf 'gh variable %s\n' "$3" >> "$FLEET_TEST_CALLS" ;;
  'secret list'|'variable list')
    printf '%s\n' ${FLEET_EXISTING_OPTIONALS:-} ;;
  'secret delete'|'variable delete')
    printf 'gh %s delete %s\n' "$1" "$3" >> "$FLEET_TEST_CALLS" ;;
  'api --method')
    cat >/dev/null || true
    printf 'gh api %s %s\n' "$3" "$4" >> "$FLEET_TEST_CALLS" ;;
  'api repos/example/fleet/environments/staging')
    printf 'gh api GET %s\n' "$2" >> "$FLEET_TEST_CALLS"
    if [ "${FLEET_INCOMPATIBLE_ENVIRONMENT:-false}" = true ]; then
      echo false
    elif [ "${FLEET_EXISTING_ENVIRONMENT:-false}" = true ]; then
      echo true
    elif [ "${FLEET_ENVIRONMENT_API_ERROR:-false}" = true ]; then
      echo 'gh: Server Error (HTTP 500)' >&2
      exit 1
    else
      echo 'gh: Not Found (HTTP 404)' >&2
      exit 1
    fi ;;
  'api repos/example/fleet/environments/staging/deployment-branch-policies')
    printf 'gh api GET %s\n' "$2" >> "$FLEET_TEST_CALLS"
    if [ "${FLEET_EXISTING_ENVIRONMENT:-false}" = true ]; then
      printf 'branch main\ntag v*\n'
      [ -z "${FLEET_EXTRA_POLICY:-}" ] || printf '%s\n' "$FLEET_EXTRA_POLICY"
    fi ;;
  'api '*)
    printf 'gh api GET %s\n' "$2" >> "$FLEET_TEST_CALLS" ;;
  *)
    printf 'Unexpected gh call: %s\n' "$*" >&2
    exit 1 ;;
esac
EOF
chmod +x "$scratch/bin/aws" "$scratch/bin/terraform" "$scratch/bin/gh"

export CONFIG_FILE="$scratch/config.env"
export FLEET_TEST_CALLS="$scratch/calls"
export PATH="$scratch/bin:$PATH"

"$root/fleet" setup --profile aws-staging > "$scratch/plan-output"
grep -q 'Next: ./fleet setup --profile aws-staging --apply' "$scratch/plan-output"
grep -q 'terraform .*infrastructure/staging init -input=false' "$scratch/calls"
grep -q 'terraform .*infrastructure/permanent plan -input=false' "$scratch/calls"
if grep -Eq '^gh (secret|variable|api PUT|api POST)' "$scratch/calls"; then
  echo 'Plan mode mutated GitHub configuration.' >&2
  exit 1
fi

# Non-interactive apply refuses to mutate either target unless every required
# deployment value was supplied up front.
: > "$scratch/calls"
unset TF_API_TOKEN FLUX_GITHUB_TOKEN GRAFANA_ADMIN_PASSWORD
if "$root/fleet" setup --profile aws-staging --apply </dev/null > "$scratch/missing-output" 2>&1; then
  echo 'Non-interactive AWS setup accepted missing deployment values.' >&2
  exit 1
fi
grep -q 'TF_API_TOKEN must be exported' "$scratch/missing-output"
if grep -Eq '^gh (secret|variable|api PUT|api POST)' "$scratch/calls"; then
  echo 'Incomplete AWS setup mutated GitHub configuration.' >&2
  exit 1
fi

: > "$scratch/calls"
export TF_API_TOKEN='test-terraform-token'
export FLUX_GITHUB_TOKEN='test-flux-token'
export GRAFANA_ADMIN_PASSWORD='test-grafana-password'
"$root/fleet" setup --profile aws-staging --apply > "$scratch/apply-output"

grep -q 'AWS staging onboarding is configured for example/fleet.' "$scratch/apply-output"
for secret in \
  AWS_GITHUB_ACTIONS_ROLE_ARN \
  TF_API_TOKEN \
  TF_CLOUD_ORGANIZATION \
  FLUX_GITHUB_TOKEN \
  GRAFANA_ADMIN_PASSWORD; do
  grep -q "^gh secret $secret bytes=" "$scratch/calls" || {
    echo "AWS onboarding omitted $secret." >&2
    exit 1
  }
done
for variable in \
  TF_WORKSPACE_PERMANENT \
  TF_WORKSPACE_STAGING \
  EKS_ADMIN_PRINCIPAL_ARNS_JSON \
  COST_OWNER; do
  grep -q "^gh variable $variable$" "$scratch/calls" || {
    echo "AWS onboarding omitted $variable." >&2
    exit 1
  }
done
grep -q '^gh api PUT repos/example/fleet/environments/staging$' "$scratch/calls"
if grep -qE 'test-(terraform|flux|grafana)' \
  "$scratch/calls" "$scratch/plan-output" "$scratch/apply-output"; then
  echo 'AWS onboarding exposed a credential in logs or output.' >&2
  exit 1
fi

# A repeat setup preserves an existing Environment instead of replacing its
# reviewers or wait timer.
: > "$scratch/calls"
export FLEET_EXISTING_ENVIRONMENT=true
"$root/fleet" setup --profile aws-staging --apply > "$scratch/repeat-output"
if grep -q '^gh api PUT repos/example/fleet/environments/staging$' "$scratch/calls"; then
  echo 'Repeat AWS setup replaced an existing GitHub Environment.' >&2
  exit 1
fi
if grep -q '^gh api POST ' "$scratch/calls"; then
  echo 'Repeat AWS setup duplicated existing deployment policies.' >&2
  exit 1
fi
unset FLEET_EXISTING_ENVIRONMENT

# Environment policies are the OIDC ref boundary. A broader or mistyped policy
# stops setup before any mutation, in plan mode too.
for extra in 'branch *' 'tag main'; do
  : > "$scratch/calls"
  export FLEET_EXISTING_ENVIRONMENT=true FLEET_EXTRA_POLICY=$extra
  if "$root/fleet" setup --profile aws-staging > "$scratch/policy-output" 2>&1; then
    echo "AWS setup accepted an unexpected Environment policy: $extra" >&2
    exit 1
  fi
  grep -q 'admits refs other than branch main and tag v\*' "$scratch/policy-output"
  if grep -Eq '^gh (secret|variable|api PUT|api POST)|^terraform ' "$scratch/calls"; then
    echo 'AWS setup mutated or planned past an unexpected Environment policy.' >&2
    exit 1
  fi
done
unset FLEET_EXISTING_ENVIRONMENT FLEET_EXTRA_POLICY

# Only a confirmed 404 creates the Environment; any other read failure stops.
: > "$scratch/calls"
export FLEET_ENVIRONMENT_API_ERROR=true
if "$root/fleet" setup --profile aws-staging --apply > "$scratch/api-error-output" 2>&1; then
  echo 'AWS setup continued after an Environment read failure.' >&2
  exit 1
fi
grep -q 'HTTP 500' "$scratch/api-error-output"
if grep -Eq '^gh (secret|variable|api PUT|api POST)' "$scratch/calls"; then
  echo 'AWS setup mutated GitHub after an Environment read failure.' >&2
  exit 1
fi
unset FLEET_ENVIRONMENT_API_ERROR

# Optional settings removed from config.env are removed from the repository.
: > "$scratch/calls"
export FLEET_EXISTING_OPTIONALS='APP_HOSTNAME ACME_EMAIL CLOUDFLARE_API_TOKEN'
"$root/fleet" setup --profile aws-staging --apply > /dev/null
for stale in 'secret delete CLOUDFLARE_API_TOKEN' 'variable delete APP_HOSTNAME' 'variable delete ACME_EMAIL'; do
  grep -q "^gh $stale$" "$scratch/calls" || { echo "AWS setup retained stale $stale." >&2; exit 1; }
done
if grep -q 'delete LOAD_HARNESS_API_KEY' "$scratch/calls"; then
  echo 'AWS setup deleted an optional value that was never set.' >&2
  exit 1
fi
unset FLEET_EXISTING_OPTIONALS

# An existing Environment with a different branch-policy mode is owned by the
# repository administrator. Setup refuses to replace it or proceed into AWS.
: > "$scratch/calls"
export FLEET_INCOMPATIBLE_ENVIRONMENT=true
if "$root/fleet" setup --profile aws-staging --apply > "$scratch/incompatible-output" 2>&1; then
  echo 'AWS setup replaced an incompatible GitHub Environment.' >&2
  exit 1
fi
grep -q 'setup will not replace them' "$scratch/incompatible-output"
if grep -Eq '^gh (secret|variable|api PUT|api POST)' "$scratch/calls"; then
  echo 'Incompatible AWS setup mutated GitHub configuration.' >&2
  exit 1
fi
if grep -q 'infrastructure/permanent apply' "$scratch/calls"; then
  echo 'Incompatible AWS setup reached the permanent Terraform apply.' >&2
  exit 1
fi
unset FLEET_INCOMPATIBLE_ENVIRONMENT

cat > "$scratch/bad-json.env" <<'EOF'
GITHUB_REPOSITORY=example/fleet
GITHUB_DEPLOYMENT_BRANCH=main
GITHUB_DEPLOYMENT_ENVIRONMENT=staging
TF_CLOUD_ORGANIZATION=example
TF_WORKSPACE_PERMANENT=infra-fleet-permanent
TF_WORKSPACE_STAGING=infra-fleet-staging
EKS_ADMIN_PRINCIPAL_ARNS_JSON='[not-json]'
EOF
if CONFIG_FILE="$scratch/bad-json.env" "$root/fleet" setup --profile aws-staging > "$scratch/bad-json-output" 2>&1; then
  echo 'AWS setup accepted a malformed EKS admin principal list.' >&2
  exit 1
fi
grep -q 'JSON array of IAM ARN strings' "$scratch/bad-json-output"

cat > "$scratch/invalid.env" <<'EOF'
GITHUB_REPOSITORY=example/fleet
GITHUB_DEPLOYMENT_BRANCH=feature/unsafe
GITHUB_DEPLOYMENT_ENVIRONMENT=staging
TF_CLOUD_ORGANIZATION=example
TF_WORKSPACE_PERMANENT=infra-fleet-permanent
TF_WORKSPACE_STAGING=infra-fleet-staging
EOF
: > "$scratch/calls"
if CONFIG_FILE="$scratch/invalid.env" "$root/fleet" up --profile aws-staging > "$scratch/invalid-output" 2>&1; then
  echo 'AWS dispatch accepted an unsupported deployment branch.' >&2
  exit 1
fi
grep -q 'support GITHUB_DEPLOYMENT_BRANCH=main only' "$scratch/invalid-output"
[ ! -s "$scratch/calls" ] || { echo 'Invalid AWS target reached an external command.' >&2; exit 1; }

echo 'AWS onboarding and dispatch boundaries passed without external calls.'
