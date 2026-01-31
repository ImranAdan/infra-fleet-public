#!/usr/bin/env bash
#
# One-time setup for GitHub Actions self-hosted runner
#
# Usage:
#   ./ops/setup-runner.sh
#
# Prerequisites:
#   - Go to GitHub: Settings → Actions → Runners → New self-hosted runner
#   - Copy the token shown (valid for 1 hour)
#

set -euo pipefail

RUNNER_DIR="$HOME/actions-runner"
REPO_URL="https://github.com/your-org/infra-fleet"

# Detect architecture
if [[ $(uname -m) == "arm64" ]]; then
    RUNNER_ARCH="arm64"
else
    RUNNER_ARCH="x64"
fi

# Latest runner version (check https://github.com/actions/runner/releases)
RUNNER_VERSION="2.321.0"
RUNNER_FILE="actions-runner-osx-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
RUNNER_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_FILE}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🏃 GitHub Actions Self-Hosted Runner Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Architecture: ${RUNNER_ARCH}"
echo "Runner dir:   ${RUNNER_DIR}"
echo "Repository:   ${REPO_URL}"
echo ""

# Check if already set up
if [[ -f "$RUNNER_DIR/.runner" ]]; then
    echo "⚠️  Runner already configured at $RUNNER_DIR"
    echo "   To reconfigure, run: rm -rf $RUNNER_DIR && ./ops/setup-runner.sh"
    echo ""
    echo "   To start the runner, run: ./ops/start-runner.sh"
    exit 0
fi

# Create directory
echo "📁 Creating runner directory..."
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# Download runner
echo "📥 Downloading runner v${RUNNER_VERSION}..."
curl -sL -o "$RUNNER_FILE" "$RUNNER_URL"

# Extract
echo "📦 Extracting..."
tar xzf "$RUNNER_FILE"
rm "$RUNNER_FILE"

# Get token from user
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔑 Runner Registration Token Required"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Go to: https://github.com/your-org/infra-fleet/settings/actions/runners/new"
echo "2. Select 'macOS' and your architecture (${RUNNER_ARCH})"
echo "3. Copy the token from the './config.sh' command shown"
echo "   (It looks like: ABCDEFG1234567...)"
echo ""
read -p "Paste your token here: " RUNNER_TOKEN

if [[ -z "$RUNNER_TOKEN" ]]; then
    echo "❌ No token provided. Exiting."
    exit 1
fi

# Configure runner
echo ""
echo "⚙️  Configuring runner..."
./config.sh \
    --url "$REPO_URL" \
    --token "$RUNNER_TOKEN" \
    --name "local-mac-$(hostname -s)" \
    --labels "self-hosted,macOS,${RUNNER_ARCH},local" \
    --work "_work" \
    --unattended

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Runner Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "To start the runner:"
echo "  ./ops/start-runner.sh"
echo ""
echo "To verify in GitHub:"
echo "  https://github.com/your-org/infra-fleet/settings/actions/runners"
echo ""
echo "The runner will appear as: local-mac-$(hostname -s)"
echo ""
