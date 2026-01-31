#!/bin/bash
# --------------------------------------------------------------------------------------------------
# Unified Port-Forward Utility
# Provides easy access to cluster services via kubectl port-forward.
# Usage: ./port-forward.sh <service>
# Available services: grafana, prometheus, alertmanager, load-harness
# --------------------------------------------------------------------------------------------------

set -e

# Service configuration: namespace:service-name:local-port:remote-port
declare -A SERVICES=(
    ["grafana"]="observability:kube-prometheus-stack-grafana:3000:80"
    ["prometheus"]="observability:kube-prometheus-stack-prometheus:9090:9090"
    ["alertmanager"]="observability:kube-prometheus-stack-alertmanager:9093:9093"
    ["load-harness"]="applications:load-harness:8080:80"
)

show_usage() {
    echo "Usage: $0 <service>"
    echo ""
    echo "Available services:"
    echo "  grafana       - Grafana dashboards (localhost:3000)"
    echo "  prometheus    - Prometheus metrics (localhost:9090)"
    echo "  alertmanager  - Alertmanager UI (localhost:9093)"
    echo "  load-harness  - Load Harness app (localhost:8080)"
    exit 1
}

show_grafana_info() {
    echo "  Grafana UI: http://localhost:3000"
    echo "  Username: admin"
    echo "  Password: Run 'kubectl get secret -n observability kube-prometheus-stack-grafana -o jsonpath=\"{.data.admin-password}\" | base64 -d'"
}

show_prometheus_info() {
    echo "  Prometheus UI: http://localhost:9090"
    echo "  Targets: http://localhost:9090/targets"
    echo "  Query: http://localhost:9090/graph"
}

show_alertmanager_info() {
    echo "  Alertmanager UI: http://localhost:9093"
    echo "  Alerts: http://localhost:9093/#/alerts"
}

show_load_harness_info() {
    echo "  Load Harness: http://localhost:8080"
    echo "  Health: http://localhost:8080/health"
    echo "  Metrics: http://localhost:8080/metrics"
    echo "  CPU Load: http://localhost:8080/load/cpu"
    echo "  Memory Load: http://localhost:8080/load/memory"
}

# Validate input
[[ -z "$1" ]] && show_usage
[[ -z "${SERVICES[$1]}" ]] && { echo "Error: Unknown service '$1'"; echo ""; show_usage; }

SERVICE="$1"
IFS=':' read -r NAMESPACE SVC_NAME LOCAL_PORT REMOTE_PORT <<< "${SERVICES[$SERVICE]}"

echo "Setting up port-forward to $SERVICE..."
echo ""

# Show service-specific information
case "$SERVICE" in
    grafana)      show_grafana_info ;;
    prometheus)   show_prometheus_info ;;
    alertmanager) show_alertmanager_info ;;
    load-harness) show_load_harness_info ;;
esac

echo ""
echo "Press Ctrl+C to stop port-forwarding"
echo ""

kubectl port-forward -n "$NAMESPACE" "svc/$SVC_NAME" "$LOCAL_PORT:$REMOTE_PORT"
