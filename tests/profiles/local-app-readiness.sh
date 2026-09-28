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
sleep() { SECONDS=$((SECONDS + 1)); }

# Waiting for a test revision records the spec Flagger analyses for it.
printf '0\n' > "$phase_count"
kctl() {
  printf '%s\n' "$(($(cat "$phase_count") + 1))" > "$phase_count"
  case "$(cat "$phase_count")" in
    1) printf 'original-spec Succeeded' ;;
    2) printf 'test-spec Progressing' ;;
    *) printf 'test-spec Succeeded' ;;
  esac
}
FLEET_TEST_SPECS=""
SECONDS=0
test_wait_phase Succeeded 10
[ "$FLEET_TEST_SPECS" = " test-spec" ] || {
  echo "Test revision specs were not recorded: '$FLEET_TEST_SPECS'." >&2
  exit 1
}

# Restoration can start from a test revision's stale Succeeded or Failed, and
# the restored revision's spec is new: each local commit changes the
# Deployment, so its hash is unknown until Flagger applies it.
printf '0\n' > "$phase_count"
kctl() {
  printf '%s\n' "$(($(cat "$phase_count") + 1))" > "$phase_count"
  case "$(cat "$phase_count")" in
    1) printf 'test-spec Succeeded' ;;
    2) printf 'test-spec Failed' ;;
    3) printf 'restored-spec Progressing' ;;
    *) printf 'restored-spec Succeeded' ;;
  esac
}
SECONDS=0
test_wait_restored 10
[ "$(cat "$phase_count")" -eq 4 ] || {
  echo 'Restoration accepted a stale test phase or missed the restored spec.' >&2
  exit 1
}

# Nothing test-related was applied: the original is still settled.
FLEET_TEST_SPECS=""
printf '0\n' > "$phase_count"
kctl() {
  printf '%s\n' "$(($(cat "$phase_count") + 1))" > "$phase_count"
  printf 'original-spec Succeeded'
}
SECONDS=0
test_wait_restored 10
[ "$(cat "$phase_count")" -eq 1 ] || {
  echo 'An untouched cluster did not settle immediately.' >&2
  exit 1
}

FLEET_TEST_SPECS=" test-spec"
kctl() {
  case "$*" in
    *describe*) : ;;
    *) printf 'test-spec Succeeded' ;;
  esac
}
SECONDS=0
if test_wait_restored 3 2> "$error_log"; then
  echo 'Restoration accepted a revision Flagger never left.' >&2
  exit 1
fi
grep -Fq 'did not settle on the original revision within 3s' "$error_log"

echo 'local application readiness contract passed'
