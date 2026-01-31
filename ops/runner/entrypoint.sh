#!/bin/bash
#
# Entrypoint for GitHub Actions self-hosted runner container
#
# Required environment variables:
#   GITHUB_TOKEN - Personal access token or runner registration token
#
# Optional environment variables:
#   RUNNER_NAME       - Name for the runner (default: docker-runner)
#   RUNNER_LABELS     - Comma-separated labels (default: self-hosted,Linux,X64,docker)
#   GITHUB_REPOSITORY - Repository to register with (default: your-org/infra-fleet)
#   GITHUB_PAT        - PAT for runner de-registration on shutdown (optional)
#

set -euo pipefail

# Configuration
REPO_URL="https://github.com/${GITHUB_REPOSITORY:-your-org/infra-fleet}"
RUNNER_NAME="${RUNNER_NAME:-docker-runner-$(hostname)}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,Linux,X64,docker}"
RUNNER_WORKDIR="_work"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🐳 GitHub Actions Runner (Docker)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Repository:   ${REPO_URL}"
echo "Runner name:  ${RUNNER_NAME}"
echo "Labels:       ${RUNNER_LABELS}"
echo ""

# Check for required token
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "❌ ERROR: GITHUB_TOKEN environment variable is required"
    echo ""
    echo "You can provide either:"
    echo "  1. A runner registration token (from GitHub Settings → Actions → Runners)"
    echo "  2. A personal access token with 'repo' scope"
    echo ""
    echo "Example:"
    echo "  docker run -e GITHUB_TOKEN=your-token infra-fleet-runner"
    exit 1
fi

# Get registration token if using PAT
# If the token starts with 'ghp_' or 'github_pat_', it's a PAT and we need to exchange it
if [[ "${GITHUB_TOKEN}" == ghp_* ]] || [[ "${GITHUB_TOKEN}" == github_pat_* ]]; then
    echo "🔑 Exchanging PAT for runner registration token..."

    # Retry up to 3 times with backoff for transient network failures
    for attempt in {1..3}; do
        REG_TOKEN_RESPONSE=$(curl -sX POST \
            -H "Authorization: token ${GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github.v3+json" \
            "https://api.github.com/repos/${GITHUB_REPOSITORY:-your-org/infra-fleet}/actions/runners/registration-token") || true

        REG_TOKEN=$(echo "$REG_TOKEN_RESPONSE" | jq -r '.token // empty')

        if [[ -n "$REG_TOKEN" ]]; then
            break
        fi

        if [[ $attempt -lt 3 ]]; then
            echo "⚠️  Attempt $attempt failed, retrying in $((attempt * 2)) seconds..."
            sleep $((attempt * 2))
        else
            echo "❌ Failed to get registration token after 3 attempts. Response:"
            echo "$REG_TOKEN_RESPONSE" | jq .
            exit 1
        fi
    done

    GITHUB_TOKEN="$REG_TOKEN"
    echo "✅ Got registration token"
fi

# Cleanup function for graceful shutdown
cleanup() {
    echo ""
    echo "🛑 Shutting down runner..."

    if [[ -e ".runner" ]]; then
        # Get a removal token
        if [[ -n "${GITHUB_PAT:-}" ]]; then
            REMOVE_TOKEN=$(curl -sX POST \
                -H "Authorization: token ${GITHUB_PAT}" \
                -H "Accept: application/vnd.github.v3+json" \
                "https://api.github.com/repos/${GITHUB_REPOSITORY:-your-org/infra-fleet}/actions/runners/remove-token" \
                | jq -r '.token // empty')

            if [[ -n "$REMOVE_TOKEN" ]]; then
                ./config.sh remove --token "$REMOVE_TOKEN" || true
            fi
        fi
    fi

    exit 0
}

trap cleanup SIGTERM SIGINT

# Configure runner if not already configured
if [[ ! -e ".runner" ]]; then
    echo "⚙️  Configuring runner..."
    ./config.sh \
        --url "$REPO_URL" \
        --token "$GITHUB_TOKEN" \
        --name "$RUNNER_NAME" \
        --labels "$RUNNER_LABELS" \
        --work "$RUNNER_WORKDIR" \
        --unattended \
        --replace
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Runner configured and starting..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "View in GitHub:"
echo "  https://github.com/${GITHUB_REPOSITORY:-your-org/infra-fleet}/settings/actions/runners"
echo ""

# Start the runner
exec ./run.sh
