#!/usr/bin/env bash
# Teardown authority is bound to the live kind instance, not only its name.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/state"
printf 'running\n' > "$scratch/cluster-state"
printf '%064d\n' 1 > "$scratch/node-id"

cat > "$scratch/bin/kind" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  'get clusters')
    [ -s "$FLEET_TEST_CLUSTER_STATE" ] && echo infra-fleet-local
    ;;
  'get nodes')
    echo infra-fleet-local-control-plane
    ;;
  'get kubeconfig')
    echo 'apiVersion: v1'
    ;;
  'delete cluster')
    : > "$FLEET_TEST_CLUSTER_STATE"
    ;;
  *)
    echo "Unexpected kind call: $*" >&2
    exit 2
    ;;
esac
EOF

cat > "$scratch/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = inspect ] && [ "${*: -1}" = infra-fleet-local-control-plane ]; then
  cat "$FLEET_TEST_NODE_ID"
  exit 0
fi
exit 1
EOF

chmod +x "$scratch/bin/kind" "$scratch/bin/docker"
export FLEET_TEST_CLUSTER_STATE="$scratch/cluster-state"
export FLEET_TEST_NODE_ID="$scratch/node-id"
export PATH="$scratch/bin:$PATH"

cd "$root"
fleet_root=$root
# shellcheck source=scripts/fleet-profiles/local.sh
source "$root/scripts/fleet-profiles/local.sh"
FLEET_STATE="$scratch/state"

local_record_cluster
local_existing_cluster

printf '%064d\n' 2 > "$scratch/node-id"
if local_existing_cluster > "$scratch/output" 2>&1; then
  echo 'A replacement cluster was accepted by a stale ownership record.' >&2
  exit 1
fi
grep -q 'does not match this workspace ownership record' "$scratch/output"

printf '%064d\n' 1 > "$scratch/node-id"
local_down >/dev/null
[ ! -e "$FLEET_STATE/cluster-owned" ]
[ ! -s "$scratch/cluster-state" ]

echo 'Local cluster ownership is bound to the live kind instance.'
