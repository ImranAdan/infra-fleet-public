#!/usr/bin/env bash
set -euo pipefail
profile=${1:-}
case "$profile" in local|aws-staging) ;; *) echo 'Unsupported deployment profile.' >&2; exit 2 ;; esac
repository_root=$(git rev-parse --show-toplevel)
cd "$repository_root"
components=(infrastructure policies applications)
image_registry=123456789012.dkr.ecr.eu-west-2.amazonaws.com
traffic_provider=nginx
if [ "$profile" = local ]; then
  components+=(routing)
  image_registry=fleet-local-registry:5000
  traffic_provider=gatewayapi:v1
else
  components+=(configuration)
fi
for component in "${components[@]}"; do
  printf '%s\n' '---'
  kubectl kustomize "k8s/profiles/$profile/$component"
done | sed \
  -e "s|\${IMAGE_REGISTRY}|$image_registry|g" \
  -e 's|${IMAGE_TAG}|git-validation|g' \
  -e 's|${ECR_REGISTRY}|123456789012.dkr.ecr.eu-west-2.amazonaws.com|g' \
  -e 's|${APP_HOSTNAME}|localhost|g' \
  -e 's|${ACME_EMAIL}|owner@example.test|g' \
  -e 's|${RUNTIME_CONFIG_REVISION}|validation|g' \
  -e 's|${VPC_ID}|vpc-0123456789abcdef0|g' \
  -e 's|${CLUSTER_NAME}|staging|g' \
  -e 's|${AWS_REGION}|eu-west-2|g' \
  -e 's|${AWS_ACCOUNT_ID}|123456789012|g' \
  -e 's|${ENVIRONMENT}|staging|g' \
  -e "s|\${TRAFFIC_PROVIDER}|$traffic_provider|g" \
  -e 's|${TRAFFIC_ENDPOINT}|validation-gateway.example.test|g'
