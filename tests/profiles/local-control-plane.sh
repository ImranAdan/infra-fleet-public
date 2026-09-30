#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# Read by the sourced strategy module.
# shellcheck disable=SC2034
fleet_root=$root
# shellcheck source=../../scripts/fleet-profiles/local.sh
source "$root/scripts/fleet-profiles/local.sh"

calls=$(mktemp)
trap 'rm -f "$calls"' EXIT
local_contract_value() { printf 'sample'; }
kctl() {
  case "$*" in
    'get kustomization app-sample -n flux-system') return 0 ;;
    *'get kustomizations -n flux-system -l infra-fleet.io/launched-app'*'index .metadata.labels'*)
      printf '\nz\n\nz\n\n' ;;
    *'get kustomizations -n flux-system -l infra-fleet.io/launched-app'*)
      printf '\napp-z-platform\n\napp-z\n\n' ;;
    *) printf 'kctl %s\n' "$*" >> "$calls" ;;
  esac
}
fctl() { printf 'fctl %s\n' "$*" >> "$calls"; }
local_wait_canary() { printf 'wait %s\n' "$1" >> "$calls"; }

local_handoff_selected_app
expected='kctl delete kustomization app-sample-platform -n flux-system --ignore-not-found --wait=true --timeout=3m
kctl delete kustomization app-sample -n flux-system --ignore-not-found --wait=true --timeout=3m'
[ "$(cat "$calls")" = "$expected" ] || {
  echo 'Selected-app ownership handoff did not prune platform then app.' >&2
  cat "$calls" >&2
  exit 1
}

: > "$calls"
local_suspend_launched_apps
local_resume_launched_apps
grep -Fxq 'fctl suspend kustomization app-z-platform' "$calls"
grep -Fxq 'fctl suspend kustomization app-z' "$calls"
resume=$(grep -E '^(fctl resume|wait )' "$calls")
expected='fctl resume kustomization app-z --timeout=15m
fctl resume kustomization app-z-platform --timeout=15m
wait z'
[ "$resume" = "$expected" ] || {
  echo 'Launched app layers did not resume app before platform.' >&2
  printf '%s\n' "$resume" >&2
  exit 1
}

echo 'local control-plane lifecycle contract passed'
