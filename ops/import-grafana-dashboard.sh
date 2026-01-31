#!/bin/bash
# Import Grafana Dashboards
# Usage: ./import-grafana-dashboard.sh
#
# Prerequisites:
#   - kubectl port-forward to Grafana running (use ./local-forward.sh)
#   - Grafana accessible at localhost:3000

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-prom-operator}"

# Dashboard files to import
DASHBOARDS=(
    "applications/load-harness/monitoring/grafana-dashboard.json"
    "applications/load-harness/monitoring/load-testing-overview.json"
    "applications/load-harness/monitoring/dora-metrics.json"
)

# Get script directory to find dashboard relative to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "${CYAN}Grafana Dashboard Import${NC}"
echo "========================="
echo ""
echo -e "${CYAN}Grafana URL:${NC} $GRAFANA_URL"
echo -e "${CYAN}Dashboards to import:${NC} ${#DASHBOARDS[@]}"
echo ""

# Check if Grafana is accessible
echo -e "${CYAN}Checking Grafana connectivity...${NC}"
if ! curl -s -o /dev/null -w "%{http_code}" "$GRAFANA_URL/api/health" | grep -q "200"; then
    echo -e "${RED}Error: Cannot connect to Grafana at $GRAFANA_URL${NC}"
    echo ""
    echo "Make sure port-forward is running:"
    echo "  ./ops/local-forward.sh"
    exit 1
fi
echo -e "${GREEN}✓ Grafana is accessible${NC}"
echo ""

# Track import results
IMPORTED=0
FAILED=0

# Import each dashboard
for DASHBOARD_PATH in "${DASHBOARDS[@]}"; do
    DASHBOARD_FILE="$REPO_ROOT/$DASHBOARD_PATH"
    DASHBOARD_NAME=$(basename "$DASHBOARD_PATH" .json)

    echo -e "${CYAN}Importing:${NC} $DASHBOARD_NAME"

    # Check if dashboard file exists
    if [ ! -f "$DASHBOARD_FILE" ]; then
        echo -e "${YELLOW}  ⚠ File not found, skipping: $DASHBOARD_FILE${NC}"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Import dashboard via API
    RESPONSE=$(curl -s -X POST \
        -u "$GRAFANA_USER:$GRAFANA_PASSWORD" \
        -H "Content-Type: application/json" \
        -d @"$DASHBOARD_FILE" \
        "$GRAFANA_URL/api/dashboards/db")

    # Check response
    STATUS=$(echo "$RESPONSE" | jq -r '.status // "error"')
    if [ "$STATUS" = "success" ]; then
        DASHBOARD_URL=$(echo "$RESPONSE" | jq -r '.url')
        DASHBOARD_UID=$(echo "$RESPONSE" | jq -r '.uid')
        echo -e "${GREEN}  ✓ Imported: $GRAFANA_URL$DASHBOARD_URL${NC}"
        IMPORTED=$((IMPORTED + 1))
    else
        MESSAGE=$(echo "$RESPONSE" | jq -r '.message // "Unknown error"')
        echo -e "${RED}  ✗ Error: $MESSAGE${NC}"
        FAILED=$((FAILED + 1))
    fi
done

# Summary
echo ""
echo "========================="
echo -e "${CYAN}Import Summary${NC}"
echo "========================="
echo -e "  Imported: ${GREEN}$IMPORTED${NC}"
echo -e "  Failed:   ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -gt 0 ]; then
    exit 1
fi
