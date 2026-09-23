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

# The teardown workflow asks a human to type its target. Show the target and
# pass on what the operator typed, never a confirmation supplied by this script.
aws_down() {
  local confirmation=${FLEET_CONFIRM_DESTROY:-}
  aws_profile_load_config "$fleet_root"
  echo "Teardown target: $GITHUB_REPOSITORY (environment $GITHUB_DEPLOYMENT_ENVIRONMENT) via nightly-destroy.yml"
  echo 'Billable staging resources are destroyed; the permanent OIDC/ECR foundation is kept.'
  if [ -z "$confirmation" ]; then
    if [ ! -t 0 ]; then
      echo 'Set FLEET_CONFIRM_DESTROY to "destroy staging" for non-interactive teardown.' >&2
      return 1
    fi
    read -r -p 'Type "destroy staging" to confirm: ' confirmation
  fi
  if [ "$confirmation" != 'destroy staging' ]; then
    echo 'Teardown not confirmed; nothing was dispatched.' >&2
    return 1
  fi
  aws_dispatch nightly-destroy.yml --field "confirm_destroy=$confirmation"
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
    down) aws_down ;;
    status)
      aws_profile_load_config "$fleet_root"
      exec gh run list --repo "$GITHUB_REPOSITORY" --workflow rebuild-stack.yml --limit 5 ;;
    *) echo "$action is available only for the local profile." >&2; return 2 ;;
  esac
}
