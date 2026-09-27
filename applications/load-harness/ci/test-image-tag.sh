#!/usr/bin/env bash

set -euo pipefail

repository_root=$(git rev-parse --show-toplevel)
cd "$repository_root"

expected_version=$(jq -er '.["applications/load-harness"]' .release-please-manifest.json)

actual=$(env GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v2.3.4 applications/load-harness/ci/image-tag.sh)
test "$actual" = "v2.3.4"

actual=$(env GITHUB_REF_TYPE=branch PUBLISH_TO_ECR=true applications/load-harness/ci/image-tag.sh)
test "$actual" = "v$expected_version"

actual=$(env GITHUB_REF_TYPE=branch GITHUB_SHA=0123456789abcdef applications/load-harness/ci/image-tag.sh)
test "$actual" = "pr-01234567"

if env GITHUB_REF_TYPE=tag GITHUB_REF_NAME=latest applications/load-harness/ci/image-tag.sh >/dev/null 2>&1; then
  echo "A floating release tag must be rejected." >&2
  exit 1
fi

if env GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v01.2.3 applications/load-harness/ci/image-tag.sh >/dev/null 2>&1; then
  echo "A release tag with a leading zero must be rejected." >&2
  exit 1
fi

invalid_manifest=$(mktemp)
trap 'rm "$invalid_manifest"' EXIT
printf '%s\n' '{"applications/load-harness":"01.2.3"}' > "$invalid_manifest"
if env GITHUB_REF_TYPE=branch PUBLISH_TO_ECR=true RELEASE_MANIFEST="$invalid_manifest" \
  applications/load-harness/ci/image-tag.sh >/dev/null 2>&1; then
  echo "A manifest version with a leading zero must be rejected." >&2
  exit 1
fi

if env GITHUB_REF_TYPE=branch GITHUB_SHA=short applications/load-harness/ci/image-tag.sh >/dev/null 2>&1; then
  echo "A malformed commit SHA must be rejected." >&2
  exit 1
fi

echo "Load Harness image tag selection passed."
