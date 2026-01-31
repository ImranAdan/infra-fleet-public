#!/bin/bash
# Port-forward all services from cluster to localhost
# Usage: ./local-forward.sh

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Kill any existing port-forwards
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping port-forwards...${NC}"
    pkill -f "kubectl port-forward" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

echo -e "${CYAN}Stopping any existing port-forwards...${NC}"
pkill -f "kubectl port-forward" 2>/dev/null || true
sleep 1

echo -e "${CYAN}Starting port-forwards...${NC}"
echo ""

# Start all port-forwards in background
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80 &>/dev/null &
PID_GRAFANA=$!

kubectl port-forward -n observability svc/kube-prometheus-stack-prometheus 9090:9090 &>/dev/null &
PID_PROMETHEUS=$!

kubectl port-forward -n applications svc/load-harness 8080:80 &>/dev/null &
PID_LOADHARNESS=$!

# Wait for port-forwards to establish
sleep 3

# Get Grafana password
GRAFANA_PASSWORD=$(kubectl get secret -n observability kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" 2>/dev/null | base64 -d || echo "prom-operator")

# Print service table
echo -e "${GREEN}All services are now accessible:${NC}"
echo ""
echo "  +--------------+-----------------------+-------------------------+"
echo "  | Service      | URL                   | Credentials             |"
echo "  +--------------+-----------------------+-------------------------+"
echo "  | Grafana      | http://localhost:3000 | admin / $GRAFANA_PASSWORD"
echo "  | Prometheus   | http://localhost:9090 | -                       |"
echo "  | Load Harness | http://localhost:8080 | -                       |"
echo "  +--------------+-----------------------+-------------------------+"
echo ""
echo -e "${CYAN}Load Harness endpoints:${NC}"
echo "  - Dashboard:        http://localhost:8080/ui"
echo "  - API Docs:         http://localhost:8080/apidocs"
echo "  - System Info:      http://localhost:8080/system/info"
echo "  - Health:           http://localhost:8080/health"
echo "  - Metrics:          http://localhost:8080/metrics"
echo "  - CPU Load:         http://localhost:8080/load/cpu"
echo "  - CPU Status:       http://localhost:8080/load/cpu/status"
echo "  - Memory Load:      http://localhost:8080/load/memory"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all port-forwards${NC}"
echo ""

# Wait for all background processes
wait $PID_GRAFANA $PID_PROMETHEUS $PID_LOADHARNESS
