#!/usr/bin/env bash
# Forward the selected app, Grafana and Prometheus from the current kube context.
set -euo pipefail

pids=()
cleanup() {
  trap - INT TERM EXIT
  if [ "${#pids[@]}" -gt 0 ]; then kill "${pids[@]}" 2>/dev/null || true; fi
}
trap cleanup INT TERM EXIT

app=$(kubectl get configmap fleet-app -n flux-system -o jsonpath='{.data.APP_NAME}')
kubectl port-forward -n observability service/kube-prometheus-stack-grafana 3000:80 &
pids+=("$!")
kubectl port-forward -n observability service/kube-prometheus-stack-prometheus 9090:9090 &
pids+=("$!")
kubectl port-forward -n applications "service/$app" 8080:80 &
pids+=("$!")

cat <<EOF
Using the current kubectl context. Press Ctrl-C to stop these forwards.

  Selected app ($app): http://localhost:8080
  Grafana:             http://localhost:3000
  Prometheus:          http://localhost:9090
EOF
wait "${pids[@]}"
