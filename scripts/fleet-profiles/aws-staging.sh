#!/usr/bin/env bash
# Sourced only by the fixed aws-staging strategy in ./fleet.

fleet_root=${fleet_root:?AWS staging profile requires the fleet root}

profile_main() {
  local action=$1 apply=$4
  case "$action" in
    setup)
      # Reads and plans by default; bootstrap-permanent.sh validates the
      # adopter configuration and prints the AWS identity before any change.
      if [ "$apply" = true ]; then
        exec "$fleet_root/scripts/bootstrap-permanent.sh" --apply
      fi
      exec "$fleet_root/scripts/bootstrap-permanent.sh" plan ;;
    up) exec gh workflow run rebuild-stack.yml --ref main ;;
    down) exec gh workflow run nightly-destroy.yml --ref main --field 'confirm_destroy=destroy staging' ;;
    status) exec gh run list --workflow rebuild-stack.yml --limit 5 ;;
    *) echo "$action is available only for the local profile." >&2; return 2 ;;
  esac
}
