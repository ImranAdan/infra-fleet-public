#!/usr/bin/env bash

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi

repository_root=$(git rev-parse --show-toplevel)
output_directory=$1

mkdir -p "$output_directory"
cp -R "$repository_root/k8s/." "$output_directory/"

while IFS= read -r -d '' manifest; do
  rendered="$manifest.rendered"
  sed \
    -e 's|${AWS_ACCOUNT_ID}|123456789012|g' \
    -e 's|${AWS_REGION}|eu-west-2|g' \
    -e 's|${CLUSTER_NAME}|staging|g' \
    -e 's|${VPC_ID}|vpc-0123456789abcdef0|g' \
    -e 's|${ENVIRONMENT}|staging|g' \
    -e 's|${ECR_REGISTRY}|123456789012.dkr.ecr.eu-west-2.amazonaws.com|g' \
    -e 's|${APP_HOSTNAME}|app.example.test|g' \
    -e 's|${ACME_EMAIL}|admin@example.test|g' \
    -e 's|${RUNTIME_CONFIG_REVISION}|local-validation|g' \
    "$manifest" > "$rendered"
  mv "$rendered" "$manifest"
done < <(find "$output_directory" -type f \( -name '*.yaml' -o -name '*.yml' \) -print0)

if grep -R -n -E '\$\{(AWS_ACCOUNT_ID|AWS_REGION|CLUSTER_NAME|VPC_ID|ENVIRONMENT|ECR_REGISTRY|APP_HOSTNAME|ACME_EMAIL|RUNTIME_CONFIG_REVISION)\}' \
  "$output_directory"; then
  echo "Known Flux substitutions remain unresolved." >&2
  exit 1
fi
