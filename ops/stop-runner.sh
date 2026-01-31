#!/usr/bin/env bash
#
# Stop the GitHub Actions self-hosted runner
#

set -euo pipefail

echo "🛑 Stopping GitHub Actions Runner..."

if pgrep -f "Runner.Listener" > /dev/null 2>&1; then
    pkill -f "Runner.Listener"
    echo "✅ Runner stopped"
else
    echo "ℹ️  Runner is not running"
fi
