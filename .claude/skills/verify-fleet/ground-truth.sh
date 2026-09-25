#!/usr/bin/env bash
# Prove the gateway golden signals count what really happened: send exactly N
# requests through the gateway, then compare the Envoy counter Prometheus holds
# before and after. Raw counters, not increase(), so the check is exact.
# Usage: ground-truth.sh [N]   Evidence: <git-common-dir>/fleet/verify/<run>/
set -euo pipefail

n=${1:-200}
[[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -gt 0 ] || { echo "Usage: $0 [N]" >&2; exit 2; }
root=$(git rev-parse --show-toplevel)
common=$(git -C "$root" rev-parse --git-common-dir)
case "$common" in /*) ;; *) common="$root/$common" ;; esac
export PATH="$common/fleet/local/bin:$PATH" KUBECONFIG="$common/fleet/local/kubeconfig"
run="ground-truth-$(date -u +%Y%m%dT%H%M%SZ)"
evidence="$common/fleet/verify/$run"
mkdir -p "$evidence"

count() {  # sum of the route's upstream requests with status $1, at unix time $2
  local url
  url=$(python3 -c 'import sys,urllib.parse
q = "sum(envoy_cluster_upstream_rq{envoy_cluster_name=~\"httproute/applications/.*\",envoy_response_code=\"%s\"})" % sys.argv[1]
print("/api/v1/namespaces/observability/services/kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?"
      + urllib.parse.urlencode({"query": q, "time": sys.argv[2]}))' "$1" "$2")
  kubectl get --raw "$url" |
    python3 -c 'import json,sys;r=json.load(sys.stdin)["data"]["result"];print(int(float(r[0]["value"][1])) if r else 0)'
}

gateway=$(kubectl get svc -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-name=fleet -o jsonpath='{.items[0].metadata.name}')
host=$(kubectl get configmap fleet-config -n flux-system -o jsonpath='{.data.APP_HOSTNAME}')
path="/verify-$run"  # a path no app serves, so every response is one known status
scrape=20            # longer than the 15 s scrape interval

t0=$(date +%s); sleep "$scrape"
# hey ignores -H 'Host: …'; -host is the flag that routes to the app.
kubectl exec -n flux-system deploy/flagger-loadtester -- \
  hey -n "$n" -c 2 -host "$host" "http://$gateway.envoy-gateway-system$path" > "$evidence/hey.txt"
sleep "$scrape"; t1=$(date +%s)

status=$(sed -n 's/^ *\[\([0-9]\{3\}\)\][[:space:]]*\([0-9]*\) responses.*/\1 \2/p' "$evidence/hey.txt")
[ "$(wc -l <<<"$status" | tr -d ' ')" = 1 ] || { echo "Expected one status code, got: $status" >&2; exit 1; }
code=${status% *} sent=${status#* }
# hey lists failed attempts under "Error distribution"; only completed
# requests reach the counter, so all N must have completed.
if [ "$sent" != "$n" ] || grep -q 'Error distribution' "$evidence/hey.txt"; then
  echo "inconclusive: $sent of $n requests completed; see $evidence/hey.txt" | tee "$evidence/verdict.txt" >&2
  exit 1
fi
before=$(count "$code" "$t0") after=$(count "$code" "$t1")
counted=$((after - before))
{
  echo "requests sent:      $sent (all $code, host $host, path $path)"
  echo "prometheus counted: $counted ($before -> $after)"
  if [ "$counted" = "$sent" ]; then echo "verdict: exact"; else echo "verdict: MISMATCH"; fi
} | tee "$evidence/verdict.txt"
echo "evidence: $evidence"
[ "$counted" = "$sent" ]
