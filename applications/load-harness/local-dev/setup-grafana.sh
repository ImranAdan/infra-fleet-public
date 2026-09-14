#!/bin/bash
# Quick setup script for Grafana datasource and dashboard
# This uses the Grafana API to automate the setup

set -e

GRAFANA_URL="http://localhost:3000"
GRAFANA_USER="admin"
GRAFANA_PASSWORD="admin"

echo "🔧 Setting up Grafana..."
echo ""

# Wait for Grafana to be ready
echo "⏳ Waiting for Grafana to be ready..."
grafana_ready=false
for _ in {1..60}; do
  if curl -s -f -o /dev/null "${GRAFANA_URL}/api/health"; then
    grafana_ready=true
    break
  fi
    printf '.'
    sleep 2
done
echo ""

if [ "$grafana_ready" != "true" ]; then
  echo "❌ Grafana did not become ready within two minutes."
  echo "   Inspect it with: ./local-dev/dev.sh logs grafana"
  exit 1
fi

echo "✅ Grafana is ready!"
echo ""

# Add Prometheus datasource
echo "📊 Adding Prometheus datasource..."
curl -X POST "${GRAFANA_URL}/api/datasources" \
  -H "Content-Type: application/json" \
  -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
  -d '{
    "name": "Prometheus",
    "type": "prometheus",
    "uid": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy",
    "isDefault": true
  }' 2>/dev/null | grep -q "Datasource added" && echo "✅ Prometheus datasource added!" || echo "ℹ️  Datasource may already exist"
echo ""

# Import dashboards
echo "📈 Importing Grafana dashboards..."
for dashboard in \
  ../monitoring/grafana-dashboard.json \
  ../monitoring/load-testing-overview.json \
  ../monitoring/dora-metrics.json; do
  if [ -f "$dashboard" ]; then
    HTTP_CODE=$(curl -X POST "${GRAFANA_URL}/api/dashboards/db" \
      -H "Content-Type: application/json" \
      -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
      -d @"$dashboard" \
      -w "%{http_code}" \
      -o /dev/null \
      -s)
    if [ "$HTTP_CODE" = "200" ]; then
      echo "✅ Imported: $(basename "$dashboard")"
    else
      echo "⚠️  Import failed: $(basename "$dashboard") (HTTP $HTTP_CODE)"
    fi
  else
    echo "ℹ️  Skipping missing dashboard: $(basename "$dashboard")"
  fi
done
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete!"
echo ""
echo "🌐 Open Grafana: ${GRAFANA_URL}"
echo "👤 Username: ${GRAFANA_USER}"
echo "🔑 Password: ${GRAFANA_PASSWORD}"
echo ""
echo "📊 Go to Dashboards → Browse to see your dashboards"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
