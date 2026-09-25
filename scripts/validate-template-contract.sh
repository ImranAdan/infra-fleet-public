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

# Code and manifests must be pinned. One line is exempt: the Fleet Application
# dashboard reads the advisor's latest approved report as data, where following
# main is the point and nothing fetched is executed. Only that exact URL, as a
# url field in that file, is allowed; any other moving URL there still fails.
approved_moving_url='^k8s/infrastructure/observability/dashboards/fleet-application\.json:[0-9]+:[[:space:]]*"url": "https://raw\.githubusercontent\.com/ImranAdan/infra-fleet-advisor-public/main/reports/report\.json",?$'
if git grep -n -E 'https://raw\.githubusercontent\.com/[^/]+/[^/]+/(main|master)/|/releases/latest/' \
  -- .github infrastructure k8s ops scripts \
  ':(exclude)scripts/validate-template-contract.sh' | grep -v -E "$approved_moving_url"; then
  echo "Executable template files must not fetch from moving branches or latest-release URLs." >&2
  failed=true
fi

if git grep -n -E "^[[:space:]]+version:[[:space:]]+['\"]?v?[0-9]+\\.x['\"]?" \
  -- k8s; then
  echo "Helm releases must use exact chart versions, not floating major ranges." >&2
  failed=true
fi

if ! jq -e 'length > 0 and all(.[]; test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))' .release-please-manifest.json >/dev/null; then
  echo "Every released application needs a semantic version in the release manifest." >&2
  failed=true
fi

# release-please advances the release manifest before the image is published;
# Flux advances the deployment only after ECR contains the release. These tags
# legitimately differ while a release is being built or deployed.
if ! grep -Eq \
  '^[[:space:]]+newTag: v[0-9]+\.[0-9]+\.[0-9]+[[:space:]]+# \{"\$imagepolicy": "flux-system:app:tag"\}[[:space:]]*$' \
  k8s/profiles/aws-staging/applications/kustomization.yaml; then
  echo "The AWS profile must retain a release tag and the Flux tag setter." >&2
  failed=true
fi

rendered_root=$(mktemp -d)
trap 'rm -rf "$rendered_root"' EXIT
./scripts/render-k8s-for-validation.sh "$rendered_root/k8s"
./tests/profiles/facade.sh
./tests/profiles/aws-onboarding.sh
./tests/profiles/local-git-snapshot.sh
./tests/profiles/cluster-ownership.sh
./tests/profiles/app-contract.sh

local_deployment_workflow=.github/workflows/local-kubernetes.yml
if grep -Eq '^  (pull_request|push):' "$local_deployment_workflow"; then
  echo "The full local deployment must not run automatically for each PR or main push." >&2
  failed=true
fi
for required_contract in \
  '^  workflow_dispatch:$' \
  '^  schedule:$' \
  '^      name: local$'; do
  if ! grep -Eq "$required_contract" "$local_deployment_workflow"; then
    echo "The local deployment workflow is missing contract: $required_contract" >&2
    failed=true
  fi
done
if ! grep -Fq 'app: ${{ fromJSON(needs.discover_apps.outputs.apps) }}' "$local_deployment_workflow"; then
  echo "The local deployment workflow must discover every shipped app contract." >&2
  failed=true
fi

while IFS= read -r -d '' shell_file; do
  bash -n "$shell_file"
done < <(find scripts ops applications -type f -name '*.sh' -print0)

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
