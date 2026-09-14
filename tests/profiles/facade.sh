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
for arguments in 'up --profile unsupported' 'up --profile ../aws-staging' 'wat --profile local' 'sync --profile aws-staging' 'up --profile aws-staging --revision abc'; do
  read -r -a fixture <<< "$arguments"
  if "$root/fleet" "${fixture[@]}" > "$scratch/output" 2>&1; then
    echo "Facade accepted invalid fixture: $arguments" >&2; exit 1
  fi
  [ ! -e "$scratch/calls" ] || { echo 'Invalid request reached GitHub.' >&2; exit 1; }
done
"$root/fleet" up --profile aws-staging
printf '%s\n' workflow run rebuild-stack.yml --ref main > "$scratch/expected"
cmp "$scratch/expected" "$scratch/calls"
"$root/fleet" down --profile aws-staging
printf '%s\n' workflow run nightly-destroy.yml --ref main --field 'confirm_destroy=destroy staging' > "$scratch/expected"
cmp "$scratch/expected" "$scratch/calls"
echo 'Facade dispatch boundaries passed (no external calls).'
