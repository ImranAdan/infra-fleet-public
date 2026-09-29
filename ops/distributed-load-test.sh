#!/usr/bin/env bash
# Drive the selected Load Harness through the same Gateway route as Flagger.
set -euo pipefail

duration=${1:-15m}
concurrency=${2:-4}
iterations=${3:-1000000}
[[ "$duration" =~ ^[1-9][0-9]*[smh]$ ]] || { echo 'Duration must look like 30s, 15m or 1h.' >&2; exit 2; }
[[ "$concurrency" =~ ^[1-9][0-9]*$ ]] || { echo 'Concurrency must be a positive integer.' >&2; exit 2; }
[[ "$iterations" =~ ^[1-9][0-9]*$ ]] || { echo 'Iterations must be a positive integer.' >&2; exit 2; }

app=$(kubectl get configmap fleet-app -n flux-system -o jsonpath='{.data.APP_NAME}')
[ "$app" = load-harness ] || {
  echo "The selected app is $app; this test requires the Load Harness contract." >&2
  exit 2
}
host=$(kubectl get configmap fleet-config -n flux-system -o jsonpath='{.data.APP_HOSTNAME}')
endpoint=$(kubectl get configmap fleet-config -n flux-system -o jsonpath='{.data.TRAFFIC_ENDPOINT}')

printf 'Distributed CPU load through Envoy Gateway\n'
printf '  Duration: %s\n  Concurrency: %s\n  Iterations: %s\n  Route: https://%s/load/cpu/work (Host: %s)\n' \
  "$duration" "$concurrency" "$iterations" "$endpoint" "$host"

kubectl exec -n flux-system deployment/flagger-loadtester -- \
  hey -z "$duration" -c "$concurrency" -m POST -host "$host" \
  -H 'Content-Type: application/json' -d "{\"iterations\": $iterations}" \
  "https://$endpoint/load/cpu/work"
