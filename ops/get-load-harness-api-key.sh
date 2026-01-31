#!/bin/bash
# Retrieve the load-harness API key from the Kubernetes cluster
#
# Usage:
#   ./ops/get-load-harness-api-key.sh [namespace]
#
# Arguments:
#   namespace - Kubernetes namespace (default: applications)
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - Secret 'load-harness-api-key' exists in the namespace

set -euo pipefail

NAMESPACE="${1:-applications}"
SECRET_NAME="load-harness-api-key"

echo "Retrieving load-harness API key from namespace: $NAMESPACE"
echo ""

# Check if secret exists
if ! kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    echo "Error: Secret '$SECRET_NAME' not found in namespace '$NAMESPACE'"
    echo ""
    echo "The secret is created during cluster rebuild. Ensure:"
    echo "  1. The cluster is running (gh workflow run rebuild-stack.yml)"
    echo "  2. LOAD_HARNESS_API_KEY is set in GitHub repository secrets"
    exit 1
fi

# Retrieve and decode the API key
API_KEY=$(kubectl get secret "$SECRET_NAME" \
    -n "$NAMESPACE" \
    -o jsonpath='{.data.api-key}' | base64 -d)

echo "✅ API key retrieved successfully (${#API_KEY} characters)"
echo ""
echo "⚠️  Security note: API key is not displayed to avoid shell history exposure"
echo ""
echo "Usage options:"
echo ""
echo "  # Option 1: Export directly to current shell (key not visible)"
echo "  export LOAD_HARNESS_API_KEY=\$(kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.api-key}' | base64 -d)"
echo ""
echo "  # Option 2: Copy to clipboard (macOS)"
echo "  kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.api-key}' | base64 -d | pbcopy"
echo ""
echo "  # Option 3: Use with curl directly"
echo "  curl -H \"X-API-Key: \$(kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.api-key}' | base64 -d)\" http://localhost:8080/"
echo ""
echo "  # For Postman/Insomnia: Use Option 2 to copy to clipboard"
