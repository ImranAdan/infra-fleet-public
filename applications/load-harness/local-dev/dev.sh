#!/bin/bash
# Developer convenience script for local development
#
# Usage:
#   ./local-dev/dev.sh up          # Start app only
#   ./local-dev/dev.sh up-full     # Start app + Prometheus + Grafana
#   ./local-dev/dev.sh down        # Stop all services
#   ./local-dev/dev.sh test        # Run tests
#   ./local-dev/dev.sh setup       # Setup Grafana (run after up-full)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

# Compose V1 is end-of-life and absent from Compose-V2-only installs, so
# resolve whichever is available rather than assuming `docker-compose`.
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "❌ Neither 'docker compose' nor 'docker-compose' is available."
  echo "   Install Docker Desktop, or the Compose plugin on Linux."
  exit 1
fi

# docker-compose.yml declares env_file: ../.env, which is gitignored. On a
# fresh clone it does not exist and Compose fails before starting anything.
# Seed it from the committed example so the documented first command works.
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "📝 Created .env from .env.example (edit it to change defaults)"
fi

case "${1:-help}" in
  up)
    echo "🚀 Starting Flask app..."
    $COMPOSE -f local-dev/docker-compose.yml up -d load-harness
    echo ""
    echo "✅ Flask app running!"
    echo "🌐 App: http://localhost:8080"
    echo "📊 Metrics: http://localhost:8080/metrics"
    echo "❤️  Health: http://localhost:8080/health"
    ;;

  up-full)
    echo "🚀 Starting full observability stack..."
    $COMPOSE -f local-dev/docker-compose.yml --profile observability up -d
    echo ""
    echo "✅ Stack running!"
    echo "🌐 Flask App: http://localhost:8080"
    echo "📊 Prometheus: http://localhost:9090"
    echo "📈 Grafana: http://localhost:3000"
    echo ""
    echo "⏳ Waiting for services to be ready..."
    sleep 5
    echo ""
    echo "💡 Run './local-dev/dev.sh setup' to configure Grafana"
    ;;

  down)
    echo "🛑 Stopping all services..."
    $COMPOSE -f local-dev/docker-compose.yml --profile observability down
    echo "✅ All services stopped"
    ;;

  test)
    echo "🧪 Running tests..."
    $COMPOSE -f local-dev/docker-compose.yml --profile test run --rm test
    ;;

  setup)
    echo "🔧 Setting up Grafana..."
    cd local-dev
    ./setup-grafana.sh
    cd ..
    ;;

  logs)
    $COMPOSE -f local-dev/docker-compose.yml --profile observability logs -f "${2:-load-harness}"
    ;;

  help|*)
    echo "Load Harness - Local Development Helper"
    echo ""
    echo "Usage: ./local-dev/dev.sh COMMAND"
    echo ""
    echo "Commands:"
    echo "  up          Start Flask app only"
    echo "  up-full     Start app + Prometheus + Grafana"
    echo "  down        Stop all services"
    echo "  test        Run tests"
    echo "  setup       Setup Grafana datasource and dashboard"
    echo "  logs [svc]  Show logs (default: load-harness)"
    echo "  help        Show this help"
    echo ""
    echo "Quick Start:"
    echo "  1. ./local-dev/dev.sh up-full   # Start everything"
    echo "  2. ./local-dev/dev.sh setup     # Configure Grafana"
    echo "  3. Open http://localhost:3000    # View dashboards"
    ;;
esac
