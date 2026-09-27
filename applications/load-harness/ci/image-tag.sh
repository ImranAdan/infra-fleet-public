#!/usr/bin/env bash

set -euo pipefail

repository_root=$(git rev-parse --show-toplevel)
manifest=${RELEASE_MANIFEST:-"$repository_root/.release-please-manifest.json"}

if [ "${GITHUB_REF_TYPE:-}" = "tag" ]; then
  image_tag=${GITHUB_REF_NAME:-}
  if [[ ! "$image_tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    echo "Release tags must use vMAJOR.MINOR.PATCH format." >&2
    exit 1
  fi
elif [ "${PUBLISH_TO_ECR:-false}" = "true" ]; then
  version=$(jq -er '.["applications/load-harness"] | strings' "$manifest")
  if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    echo "Invalid load-harness version in .release-please-manifest.json" >&2
    exit 1
  fi
  image_tag="v$version"
else
  commit_sha=${GITHUB_SHA:-}
  if [[ ! "$commit_sha" =~ ^[0-9a-fA-F]{8,}$ ]]; then
    echo "GITHUB_SHA must contain at least eight hexadecimal characters." >&2
    exit 1
  fi
  image_tag="pr-${commit_sha:0:8}"
fi

if [[ ! "$image_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo "Generated image tag is not valid for a container registry." >&2
  exit 1
fi

printf '%s\n' "$image_tag"
