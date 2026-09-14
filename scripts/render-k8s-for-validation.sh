#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "Usage: $0 OUTPUT_DIRECTORY" >&2; exit 2; fi
repository_root=$(git rev-parse --show-toplevel)
output_directory=$1
mkdir -p "$output_directory"
for profile in local aws-staging; do
  mkdir -p "$output_directory/$profile"
  "$repository_root/scripts/render-profile.sh" "$profile" > "$output_directory/$profile/resources.yaml"
  kubectl kustomize "$repository_root/k8s/clusters/$profile" > "$output_directory/$profile/flux-root.yaml"
done
if grep -R -n -E '\$\{[A-Z_]+\}' "$output_directory"; then
  echo 'Unresolved profile substitutions remain.' >&2; exit 1
fi
