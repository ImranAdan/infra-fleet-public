#!/usr/bin/env bash
# Dispatch boundaries, without a cluster, GitHub calls or AWS credentials.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin"
cat > "$scratch/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$FLEET_TEST_CALLS"
EOF
chmod +x "$scratch/bin/gh"
export FLEET_TEST_CALLS="$scratch/calls"
export PATH="$scratch/bin:$PATH"
cat > "$scratch/config.env" <<'EOF'
GITHUB_REPOSITORY=example/fleet
GITHUB_DEPLOYMENT_BRANCH=main
GITHUB_DEPLOYMENT_ENVIRONMENT=staging
TF_CLOUD_ORGANIZATION=example
TF_WORKSPACE_PERMANENT=infra-fleet-permanent
TF_WORKSPACE_STAGING=infra-fleet-staging
EKS_ADMIN_PRINCIPAL_ARNS_JSON='[]'
EOF
export CONFIG_FILE="$scratch/config.env"
for arguments in 'up --profile unsupported' 'up --profile ../aws-staging' 'wat --profile local' 'sync --profile aws-staging' 'up --profile aws-staging --revision abc' 'setup --profile unsupported' 'setup --profile ../local' 'up --profile local --apply' 'setup --profile local --apply' 'down --profile aws-staging --apply'; do
  read -r -a fixture <<< "$arguments"
  if "$root/fleet" "${fixture[@]}" > "$scratch/output" 2>&1; then
    echo "Facade accepted invalid fixture: $arguments" >&2; exit 1
  fi
  [ ! -e "$scratch/calls" ] || { echo 'Invalid request reached GitHub.' >&2; exit 1; }
done
"$root/fleet" up --profile aws-staging
printf '%s\n' workflow run rebuild-stack.yml --repo example/fleet --ref main > "$scratch/expected"
cmp "$scratch/expected" "$scratch/calls"
"$root/fleet" down --profile aws-staging
printf '%s\n' workflow run nightly-destroy.yml --repo example/fleet --ref main --field 'confirm_destroy=destroy staging' > "$scratch/expected"
cmp "$scratch/expected" "$scratch/calls"
# setup is part of the fixed action surface for both profiles.
"$root/fleet" --help > "$scratch/help"
for phase in setup up down; do
  grep -qE "^  $phase " "$scratch/help" || { echo "Facade help omits the $phase phase." >&2; exit 1; }
done

# AWS setup validates the adopter configuration before touching anything, and
# must never dispatch a workflow. CONFIG_FILE forces the check to fail here
# whether or not the machine running the test has a real config.env.
# The legitimate up/down dispatches above left a calls file; clear it so this
# assertion is about setup alone.
rm -f "$scratch/calls"
if CONFIG_FILE="$scratch/absent.env" "$root/fleet" setup --profile aws-staging > "$scratch/output" 2>&1; then
  echo 'AWS setup succeeded without configuration.' >&2; exit 1
fi
grep -q 'absent.env' "$scratch/output" || { echo 'AWS setup did not name the missing configuration.' >&2; exit 1; }
[ ! -e "$scratch/calls" ] || { echo 'AWS setup reached GitHub before validating.' >&2; exit 1; }

echo 'Facade dispatch boundaries passed (no external calls).'
