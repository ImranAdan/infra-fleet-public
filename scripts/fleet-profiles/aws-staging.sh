#!/usr/bin/env bash
# Sourced only by the fixed aws-staging strategy in ./fleet.

fleet_root=${fleet_root:?AWS staging profile requires the fleet root}
# shellcheck source=scripts/aws-profile-config.sh
source "$fleet_root/scripts/aws-profile-config.sh"

aws_dispatch() {
  local workflow=$1
  shift
  aws_profile_load_config "$fleet_root"
  exec gh workflow run "$workflow" \
    --repo "$GITHUB_REPOSITORY" \
    --ref "$GITHUB_DEPLOYMENT_BRANCH" \
    "$@"
}

profile_main() {
  local action=$1 apply=$4
  case "$action" in
    setup)
      if [ "$apply" = true ]; then
        exec "$fleet_root/scripts/onboard-aws-profile.sh" --apply
      fi
      exec "$fleet_root/scripts/onboard-aws-profile.sh" plan ;;
    up) aws_dispatch rebuild-stack.yml ;;
    down) aws_dispatch nightly-destroy.yml --field 'confirm_destroy=destroy staging' ;;
    status)
      aws_profile_load_config "$fleet_root"
      exec gh run list --repo "$GITHUB_REPOSITORY" --workflow rebuild-stack.yml --limit 5 ;;
    *) echo "$action is available only for the local profile." >&2; return 2 ;;
  esac
}
