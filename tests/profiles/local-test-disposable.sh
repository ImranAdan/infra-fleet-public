#!/usr/bin/env bash
# CI deletes its cluster after `fleet test`; restoring the original revision
# there costs a full canary cycle for nothing. A shared cluster still restores.
set -euo pipefail
# State and stubs are read only by the sourced module's EXIT handler.
# shellcheck disable=SC2034,SC2329

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

# Runs the EXIT handler after a test that failed with status 3.
restore() {
  (
    fleet_root=$root
    # shellcheck source=../../scripts/fleet-profiles/test-local.sh
    source "$root/scripts/fleet-profiles/test-local.sh"
    FLEET_STATE=$scratch FLEET_TEST_ORIGINAL=original FLEET_TEST_SPECS=test-spec
    FLEET_TEST_LAUNCHED="" FLEET_TEST_SNAPSHOT=$scratch/snapshot APP_NAME=sample
    sleep() { exit 9; }
    git() { printf 'git\n' >> "$scratch/calls"; }
    fctl() { printf 'fctl %s\n' "$1" >> "$scratch/calls"; }
    kctl() {
      case "$*" in
        'get canary'*) printf 'original-spec Succeeded' ;;
        *) printf 'kctl %s\n' "$1" >> "$scratch/calls" ;;
      esac
    }
    (exit 3) || test_restore_snapshot
  )
}

: > "$scratch/calls"
status=0; FLEET_TEST_DISPOSABLE=1 restore || status=$?
[ "$status" -eq 3 ]
[ ! -s "$scratch/calls" ] || { cat "$scratch/calls" >&2; echo 'A disposable cluster was restored.' >&2; exit 1; }

: > "$scratch/calls"
status=0; restore || status=$?
[ "$status" -eq 3 ]
grep -qx 'fctl reconcile' "$scratch/calls" || { echo 'A shared cluster was not restored.' >&2; exit 1; }

echo 'disposable local acceptance skips restoration'
