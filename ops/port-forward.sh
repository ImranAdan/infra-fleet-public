#!/bin/bash
# Unified port-forward utility. Usage: ./port-forward.sh <service>
set -e

usage() {
    cat <<'EOF'
Usage: port-forward.sh <service>

  grafana       Grafana dashboards   localhost:3000
  prometheus    Prometheus metrics   localhost:9090
  alertmanager  Alertmanager UI      localhost:9093
  load-harness  Load Harness app     localhost:8080
EOF
    exit 1
}

[ -z "${1:-}" ] && usage

# One case carries the whole per-service configuration. A case rather than an
# associative array because macOS still ships bash 3.2, where `declare -A` is a
# syntax error - an adopter on a Mac hit that before ever reaching kubectl.
case "$1" in
    grafana)
        NAMESPACE=observability SVC=kube-prometheus-stack-grafana LOCAL=3000 REMOTE=80
        LINKS="  Grafana UI: http://localhost:3000
  Username: admin
  Password: kubectl get secret -n observability grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d" ;;
    prometheus)
        NAMESPACE=observability SVC=kube-prometheus-stack-prometheus LOCAL=9090 REMOTE=9090
        LINKS="  Prometheus UI: http://localhost:9090
  Targets: http://localhost:9090/targets
  Query: http://localhost:9090/graph" ;;
    alertmanager)
        NAMESPACE=observability SVC=kube-prometheus-stack-alertmanager LOCAL=9093 REMOTE=9093
        LINKS="  Alertmanager UI: http://localhost:9093
  Alerts: http://localhost:9093/#/alerts" ;;
    load-harness)
        NAMESPACE=applications SVC=load-harness LOCAL=8080 REMOTE=80
        LINKS="  Load Harness: http://localhost:8080
  Health: http://localhost:8080/health
  Metrics: http://localhost:8080/metrics
  CPU Load: http://localhost:8080/load/cpu
  Memory Load: http://localhost:8080/load/memory" ;;
    *)
        echo "Unknown service '$1'" >&2
        echo >&2
        usage ;;
esac

echo "Setting up port-forward to $1..."
echo
echo "$LINKS"
echo
echo "Press Ctrl+C to stop port-forwarding"
echo

kubectl port-forward -n "$NAMESPACE" "svc/$SVC" "$LOCAL:$REMOTE"
