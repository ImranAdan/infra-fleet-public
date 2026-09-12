#!/usr/bin/env bash

set -euo pipefail

repository_root=$(git rev-parse --show-toplevel)
cd "$repository_root"

failed=false

while IFS= read -r workflow; do
  if ! grep -q '^permissions:' "$workflow"; then
    echo "$workflow does not declare a top-level token permission baseline." >&2
    failed=true
  fi
done < <(find .github/workflows -type f \( -name '*.yml' -o -name '*.yaml' \) | sort)

if git grep -n -E 'your-org|your-terraform-org|123456789012|app\.example\.com|admin@example\.com|user/imran|repo:[^" ]+:\*' \
  -- .github infrastructure k8s ops ':(exclude)k8s/flux-system/flux-system/gotk-sync.yaml'; then
  echo "Executable template files contain adopter-specific placeholder values." >&2
  failed=true
fi

if git grep -n -E '^[[:space:]]*(- )?uses: [^./][^ ]*@v?[0-9]+(\.[0-9]+)*([[:space:]]|$)' \
  -- '.github/**/*.yml' '.github/**/*.yaml'; then
  echo "Third-party GitHub Actions must be pinned to a full commit SHA." >&2
  failed=true
fi

if git grep -n -E 'https://raw\.githubusercontent\.com/[^/]+/[^/]+/(main|master)/|/releases/latest/' \
  -- .github infrastructure k8s ops scripts; then
  echo "Executable template files must not fetch from moving branches or latest-release URLs." >&2
  failed=true
fi

if git grep -n -E "^[[:space:]]+version:[[:space:]]+['\"]?v?[0-9]+\\.x['\"]?" \
  -- k8s; then
  echo "Helm releases must use exact chart versions, not floating major ranges." >&2
  failed=true
fi

version=$(jq -er '."applications/load-harness"' .release-please-manifest.json)
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "The release manifest does not contain a semantic load-harness version." >&2
  failed=true
elif ! grep -Fq \
  'image: ${ECR_REGISTRY}/load-harness:v'"$version" \
  k8s/applications/load-harness/deployment.yaml; then
  echo "The bootstrap deployment tag does not match the release manifest ($version)." >&2
  failed=true
fi

rendered_root=$(mktemp -d)
trap 'rm -rf "$rendered_root"' EXIT
./scripts/render-k8s-for-validation.sh "$rendered_root/k8s"

while IFS= read -r -d '' shell_file; do
  bash -n "$shell_file"
done < <(find scripts ops applications/load-harness/local-dev -type f -name '*.sh' -print0)

while IFS= read -r -d '' json_file; do
  jq empty "$json_file"
done < <(find applications . -maxdepth 4 -type f -name '*.json' -print0 | sort -zu)

if git grep -n -E 'image:[[:space:]]+[^#[:space:]]+:latest([[:space:]]|$)' \
  -- applications ops k8s; then
  echo "Runtime container images must not use mutable latest tags." >&2
  failed=true
fi

if [ "$failed" = "true" ]; then
  exit 1
fi

echo "Template contract is internally consistent."
