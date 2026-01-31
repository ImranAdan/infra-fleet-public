#!/usr/bin/env bash
#
# Start the GitHub Actions self-hosted runner
#
# Usage:
#   ./ops/start-runner.sh           # Run in foreground (see logs)
#   ./ops/start-runner.sh --background  # Run in background
#
# The runner will pick up jobs from:
#   - Pull requests
#   - Manual workflow dispatches
#   - Scheduled workflows (if running at that time)
#
# Stop with Ctrl+C (foreground) or: ./ops/stop-runner.sh
#

set -euo pipefail

RUNNER_DIR="$HOME/actions-runner"
MODE="${1:-foreground}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🏃 Starting GitHub Actions Runner"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if configured
if [[ ! -f "$RUNNER_DIR/.runner" ]]; then
    echo "❌ Runner not configured. Run setup first:"
    echo "   ./ops/setup-runner.sh"
    exit 1
fi

cd "$RUNNER_DIR"

# Check if already running
if pgrep -f "Runner.Listener" > /dev/null 2>&1; then
    echo "⚠️  Runner is already running!"
    echo "   PID: $(pgrep -f 'Runner.Listener')"
    echo ""
    echo "   To stop: ./ops/stop-runner.sh"
    exit 0
fi

echo ""
echo "Runner directory: $RUNNER_DIR"
echo "Mode: $MODE"
echo ""
echo "GitHub UI: https://github.com/your-org/infra-fleet/settings/actions/runners"
echo ""

if [[ "$MODE" == "--background" ]]; then
    echo "Starting in background..."
    nohup ./run.sh > runner.log 2>&1 &
    echo "✅ Runner started in background (PID: $!)"
    echo ""
    echo "View logs:  tail -f $RUNNER_DIR/runner.log"
    echo "Stop:       ./ops/stop-runner.sh"
else
    echo "Starting in foreground (Ctrl+C to stop)..."
    echo ""
    ./run.sh
fi
