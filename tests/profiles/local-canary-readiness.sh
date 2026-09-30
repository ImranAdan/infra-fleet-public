#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# Read by the sourced strategy module.
# shellcheck disable=SC2034
fleet_root=$root
# shellcheck source=../../scripts/fleet-profiles/local.sh
source "$root/scripts/fleet-profiles/local.sh"

FLEET_SHA=new-revision
calls=$(mktemp)
phase_count=$(mktemp)
error_log=$(mktemp)
trap 'rm -f "$calls" "$phase_count" "$error_log"' EXIT

sleep() { SECONDS=$((SECONDS + 1)); }

# A terminal phase from the previous rollout is stale until the requested
# revision reaches the generated primary.
printf '0\n' > "$phase_count"
# Invoked indirectly by local_wait_canary.
# shellcheck disable=SC2329
kctl() {
  case "$*" in
    'get deployment sample -n applications -o jsonpath={.spec.template.metadata.annotations.infra-fleet\.io/runtime-config-revision}')
      printf '%s' "$FLEET_SHA" ;;
    'get deployment sample-primary -n applications -o jsonpath={.spec.template.metadata.annotations.infra-fleet\.io/runtime-config-revision}')
      if [ "$(cat "$phase_count")" -ge 3 ]; then printf '%s' "$FLEET_SHA"; else printf 'old-revision'; fi ;;
    'get canary sample -n applications -o jsonpath={.status.phase}')
      printf '%s\n' "$(($(cat "$phase_count") + 1))" > "$phase_count"
      case "$(cat "$phase_count")" in
        1) printf 'Failed' ;;
        2) printf 'Progressing' ;;
        *) printf 'Succeeded' ;;
      esac ;;
    'get canary sample -n applications -o jsonpath={.status.lastAppliedSpec}')
      if [ "$(cat "$phase_count")" -le 1 ]; then printf 'old-spec'; else printf 'new-spec'; fi ;;
    *) printf 'kctl %s\n' "$*" >> "$calls" ;;
  esac
}

SECONDS=0
local_wait_canary sample 10 old-spec >/dev/null
[ "$(cat "$phase_count")" -eq 4 ] || {
  echo 'Canary readiness accepted a stale terminal phase.' >&2
  exit 1
}

# A rollback of the requested target is a deployment failure even though the
# previous primary is still healthy.
# shellcheck disable=SC2329
kctl() {
  case "$*" in
    'get deployment sample -n applications -o jsonpath={.spec.template.metadata.annotations.infra-fleet\.io/runtime-config-revision}') printf '%s' "$FLEET_SHA" ;;
    'get deployment sample-primary -n applications -o jsonpath={.spec.template.metadata.annotations.infra-fleet\.io/runtime-config-revision}') printf 'old-revision' ;;
    'get canary sample -n applications -o jsonpath={.status.phase}') printf 'Failed' ;;
    'get canary sample -n applications -o jsonpath={.status.lastAppliedSpec}') printf 'new-spec' ;;
    'describe canary sample -n applications') printf 'rollback evidence\n' >> "$calls" ;;
    *) return 1 ;;
  esac
}

SECONDS=0
if local_wait_canary sample 10 old-spec 2> "$error_log"; then
  echo 'Canary readiness accepted a rollback.' >&2
  exit 1
fi
grep -Fq 'sample rolled back revision new-revision.' "$error_log"
grep -Fq 'rollback evidence' "$calls"

echo 'local canary readiness contract passed'
