#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
fleet_root=$root
fail() { echo "$*" >&2; return 1; }

# shellcheck source=../../scripts/fleet-profiles/test-local.sh
source "$root/scripts/fleet-profiles/test-local.sh"

APP_NAME=sample
APP_PORT=8080
APP_HEALTH_PATH=/ready
attempts=0
error_log=$(mktemp)
phase_count=$(mktemp)
trap 'rm -f "$error_log" "$phase_count"' EXIT

kctl() {
  attempts=$((attempts + 1))
  SECONDS=$((SECONDS + 1))
  [ "$attempts" -ge 3 ]
}
sleep() { :; }

SECONDS=0
test_wait_application 5
[ "$attempts" -eq 3 ] || {
  echo "Application readiness used $attempts attempts instead of 3." >&2
  exit 1
}

kctl() {
  attempts=$((attempts + 1))
  SECONDS=$((SECONDS + 2))
  return 7
}

attempts=0
SECONDS=0
if test_wait_application 3 2> "$error_log"; then
  echo 'Application readiness accepted an endpoint that never became ready.' >&2
  exit 1
fi
grep -Fq 'sample-primary did not become healthy within 3s' "$error_log"

# Restoration can start from the test revision's stale Succeeded: Flagger sees
# the restored Deployment asynchronously, so a terminal phase alone proves
# nothing until Flagger has applied the original spec again.
printf '0\n' > "$phase_count"
kctl() {
  local count
  count=$(cat "$phase_count")
  count=$((count + 1))
  printf '%s\n' "$count" > "$phase_count"
  case "$count" in
    1) printf 'test-spec Succeeded' ;;
    2) printf 'test-spec Failed' ;;
    3) printf 'original-spec Progressing' ;;
    *) printf 'original-spec Succeeded' ;;
  esac
}
sleep() { SECONDS=$((SECONDS + 1)); }

SECONDS=0
test_wait_restored original-spec 10
[ "$(cat "$phase_count")" -eq 4 ] || {
  echo 'Restoration accepted a phase before Flagger applied the original spec.' >&2
  exit 1
}

# Nothing test-related was applied: the original spec is still in place.
printf '0\n' > "$phase_count"
kctl() {
  printf '%s\n' "$(($(cat "$phase_count") + 1))" > "$phase_count"
  printf 'original-spec Succeeded'
}
SECONDS=0
test_wait_restored original-spec 10
[ "$(cat "$phase_count")" -eq 1 ] || {
  echo 'An untouched cluster did not settle immediately.' >&2
  exit 1
}

kctl() {
  case "$*" in
    *describe*) : ;;
    *) printf 'test-spec Succeeded' ;;
  esac
}
SECONDS=0
if test_wait_restored original-spec 3 2> "$error_log"; then
  echo 'Restoration accepted a revision Flagger never applied.' >&2
  exit 1
fi
grep -Fq 'did not settle on the original revision within 3s' "$error_log"

echo 'local application readiness contract passed'
