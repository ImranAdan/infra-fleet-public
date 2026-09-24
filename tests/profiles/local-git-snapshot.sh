#!/usr/bin/env bash
# The local Git transport must accept the shallow clones used by GitHub Actions.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

# The Advisor may render a non-bootstrap Flux source only when Fleet declares
# that the source mirrors the reviewed checkout. Keep that declaration coupled
# to the exact-revision publication test below.
git_source=$(sed -n '1,/^---$/p' "$root/platform/local/flux-source.yaml")
grep -q '^kind: GitRepository$' <<< "$git_source"
grep -q '^    infra-fleet.io/checkout-mirror: "true"$' <<< "$git_source"

git clone --quiet --depth 1 "file://$root" "$scratch/shallow"
cd "$scratch/shallow"
fleet_root=$PWD
# shellcheck source=scripts/fleet-profiles/local.sh
source "$root/scripts/fleet-profiles/local.sh"
FLEET_STATE="$scratch/state"
FLEET_SHA=$(git rev-parse HEAD)

local_publish_snapshot
published_sha=$(git --git-dir="$FLEET_STATE/source/fleet.git" rev-parse refs/heads/fleet-local)
[ "$published_sha" = "$FLEET_SHA" ]

git clone --quiet --single-branch --branch fleet-local \
  "file://$FLEET_STATE/source/fleet.git" "$scratch/published"
[ "$(git -C "$scratch/published" rev-parse HEAD)" = "$FLEET_SHA" ]

echo 'Local Git snapshot publication passed from a shallow checkout.'
