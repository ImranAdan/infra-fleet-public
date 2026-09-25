#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
fleet_root=$root
# shellcheck source=../../scripts/fleet-profiles/local.sh
source "$root/scripts/fleet-profiles/local.sh"

calls=$(mktemp)
trap 'rm -f "$calls"' EXIT

kctl() {
  printf '%s\n' "$*" >> "$calls"
  if [ "$1 $2" = 'get deployment' ]; then
    printf '%s' 'envoy-fleet-abc123'
  fi
}

local_wait_gateway

grep -Fq 'wait --for=condition=Accepted gateway/fleet -n envoy-gateway-system --timeout=5m' "$calls"
grep -Fq 'rollout status deployment/envoy-fleet-abc123 -n envoy-gateway-system --timeout=5m' "$calls"
if grep -Fq 'condition=Programmed' "$calls"; then
  echo 'local_wait_gateway still trusts the stale top-level Programmed condition' >&2
  exit 1
fi

echo 'local gateway readiness contract passed'
