#!/usr/bin/env bash
# Read-only health check for the local fleet: is this instance worth driving?
# Prints one line per check (ok / warn / FAIL) and exits 1 on any FAIL.
# Every check encodes a failure met in practice; see the skill's Doctor section.
set -uo pipefail

root=$(git rev-parse --show-toplevel)
state="$(git -C "$root" rev-parse --git-common-dir)/fleet/local"
case "$state" in /*) ;; *) state="$root/$state" ;; esac
export PATH="$state/bin:$PATH" KUBECONFIG="$state/kubeconfig"
failed=0
ok() { printf 'ok    %s\n' "$*"; }
warn() { printf 'warn  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; failed=1; }
k() { kubectl --request-timeout=15s "$@"; }
prom() {
  k get --raw "/api/v1/namespaces/observability/services/kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=$1"
}

docker info >/dev/null 2>&1 || { bad 'Docker is not reachable'; exit 1; }
docker ps --format '{{.Names}}' | grep -qx infra-fleet-local-control-plane ||
  { bad 'kind node infra-fleet-local-control-plane is not running (./fleet up --profile local)'; exit 1; }
[ -s "$KUBECONFIG" ] || { bad "no fleet kubeconfig at $KUBECONFIG"; exit 1; }
k get nodes >/dev/null 2>&1 || { bad 'API server unreachable with the fleet kubeconfig'; exit 1; }
ok "cluster reachable through $KUBECONFIG (never the default kubeconfig)"

for helper in fleet-local-git fleet-local-registry; do
  if docker ps --format '{{.Names}}' | grep -qx "$helper"; then ok "$helper running"
  else bad "$helper is not running; a Docker restart stops it (./fleet up --profile local restores it)"; fi
done

revisions=$(k get kustomizations -n flux-system -o jsonpath='{range .items[*]}{.metadata.name}={.status.lastAppliedRevision}|{.status.conditions[?(@.type=="Ready")].status}|{.spec.suspend}{"\n"}{end}')
applied=$(printf '%s\n' "$revisions" | sed -n 's/^[^=]*=[^@]*@sha1:\([0-9a-f]*\)|.*/\1/p' | sort -u)
while IFS= read -r line; do
  name=${line%%=*} rest=${line#*=}; ready=$(cut -d'|' -f2 <<<"$rest"); suspended=$(cut -d'|' -f3 <<<"$rest")
  [ "$suspended" = true ] && bad "Kustomization $name is suspended (an interrupted sync; ./fleet sync or up clears it)"
  case "$ready" in
    True) ;;
    Unknown) warn "Kustomization $name is reconciling; re-run doctor once it settles" ;;
    *) bad "Kustomization $name is not Ready (kubectl describe kustomization $name -n flux-system)" ;;
  esac
done <<<"$revisions"
if [ "$(wc -l <<<"$applied" | tr -d ' ')" = 1 ] && [ -n "$applied" ]; then
  head=$(git -C "$root" rev-parse HEAD)
  if [ "$applied" = "$head" ]; then ok "every Flux layer applied $head (HEAD)"
  else warn "every Flux layer applied ${applied:0:12}; HEAD is ${head:0:12} (./fleet sync deploys HEAD)"; fi
else
  bad "Flux layers applied different revisions: $(tr '\n' ' ' <<<"$applied")"
fi

live_app=$(k get configmap fleet-app -n flux-system -o jsonpath='{.data.APP_NAME}' 2>/dev/null)
head_app=$(awk '$1 == "APP_NAME:" { print $2; exit }' "$root/k8s/fleet-app/fleet-app.yaml")
if [ -n "$live_app" ]; then ok "running app: $live_app"; else bad 'no fleet-app contract in the cluster'; fi
[ "$live_app" = "$head_app" ] || warn "checkout selects $head_app but the cluster runs $live_app"

unhealthy=$(k get pods -A --no-headers 2>/dev/null | awk '$4 != "Running" && $4 != "Completed" { print $1 "/" $2 " " $4 }')
if [ -z "$unhealthy" ]; then ok 'every pod Running or Completed'
else bad "unhealthy pods: $(tr '\n' ';' <<<"$unhealthy")"; fi

phase=$(k get canary "$live_app" -n applications -o jsonpath='{.status.phase}' 2>/dev/null)
case "$phase" in
  Initialized|Succeeded) ok "canary $live_app is $phase" ;;
  Progressing|Promoting|Finalising|Waiting) warn "canary $live_app is $phase: analysis in progress; wait before driving traffic tests" ;;
  Failed) warn "canary $live_app last rolled back (Failed); read: kubectl describe canary $live_app -n applications" ;;
  *) bad "no canary for $live_app" ;;
esac

cpu=$(k top node --no-headers 2>/dev/null | awk '{ gsub("%", "", $3); print $3 }')
if [ -z "$cpu" ]; then warn 'node CPU unknown (metrics-server not ready)'
elif [ "$cpu" -ge 70 ]; then warn "node CPU at ${cpu}%: latency tests will mislead (kubectl top pods -A --sort-by=cpu)"
else ok "node CPU at ${cpu}%"; fi

if prom 'up' >/dev/null 2>&1; then
  targets=$(prom 'count(up==1)' | sed -n 's/.*"value":\[[^,]*,"\([0-9]*\)"\].*/\1/p')
  ok "Prometheus answering through the API proxy (${targets:-0} targets up)"
else
  bad 'Prometheus not reachable through the API proxy'
fi

exit "$failed"
