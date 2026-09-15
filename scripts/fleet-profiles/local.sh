#!/usr/bin/env bash
# Sourced only by the fixed local strategy in ./fleet.

FLEET_CLUSTER=infra-fleet-local
fleet_root=${fleet_root:?Local profile requires the fleet root}
FLEET_CONTEXT=kind-infra-fleet-local
FLEET_REGISTRY=fleet-local-registry
FLEET_GIT=fleet-local-git
FLEET_STATE="$(git rev-parse --path-format=absolute --git-common-dir)/fleet/local"
FLEET_OWNER=$(printf '%s' "$(git rev-parse --path-format=absolute --git-common-dir)" | git hash-object --stdin)
FLEET_NODE_IMAGE='kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f'
FLEET_REGISTRY_IMAGE='registry:3.0.0@sha256:6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e'
FLEET_GIT_IMAGE=infra-fleet-local-git:2.49.1

kctl() { kubectl --kubeconfig "$FLEET_STATE/kubeconfig" --context "$FLEET_CONTEXT" "$@"; }
fctl() { flux --kubeconfig "$FLEET_STATE/kubeconfig" --context "$FLEET_CONTEXT" "$@"; }
fail() { echo "$*" >&2; return 1; }

local_prerequisites() {
  for binary in docker kind kubectl flux git openssl curl; do
    command -v "$binary" >/dev/null || fail "Missing $binary; see docs/LOCAL-KUBERNETES.md." || return 1
  done
  docker info >/dev/null
  mkdir -p "$FLEET_STATE"
  chmod 700 "$FLEET_STATE"
}

local_cluster_exists() { kind get clusters 2>/dev/null | grep -Fxq "$FLEET_CLUSTER"; }

local_owned_container() {
  local actual_owner
  actual_owner=$(docker inspect --format '{{index .Config.Labels "io.infra-fleet.owner"}}' "$1")
  [ "$actual_owner" = "$FLEET_OWNER" ] || fail "Container $1 belongs to another workspace; refusing to change it."
}

local_existing_cluster() {
  local_cluster_exists || fail 'Local cluster is not running; use ./fleet up --profile local.' || return 1
  [ -f "$FLEET_STATE/cluster-owned" ] || fail 'Cluster name already exists without this facade ownership record.' || return 1
  kind get kubeconfig --name "$FLEET_CLUSTER" > "$FLEET_STATE/kubeconfig"
  chmod 600 "$FLEET_STATE/kubeconfig"
}

local_revision() {
  if [ -n "$(git status --porcelain)" ]; then
    fail 'Commit the fleet changes first: local deployment uses a verified Git snapshot.'
    return 1
  fi
  FLEET_SHA=${1:-$(git rev-parse HEAD)}
  [[ "$FLEET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail '--revision must be a full lowercase Git SHA.' || return 1
  git cat-file -e "$FLEET_SHA^{commit}"
  FLEET_TAG="git-${FLEET_SHA:0:12}"
}

local_publish_snapshot() {
  local published_sha
  mkdir -p "$FLEET_STATE/source"
  if [ ! -d "$FLEET_STATE/source/fleet.git" ]; then
    git init --bare --initial-branch=fleet-local "$FLEET_STATE/source/fleet.git" >/dev/null
  fi
  # actions/checkout and many template consumers use a shallow clone. Permit
  # the destination's shallow boundary to follow that verified source commit.
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch \
    --quiet --force --update-shallow \
    "file://$fleet_root" "$FLEET_SHA:refs/heads/fleet-local"
  published_sha=$(git --git-dir="$FLEET_STATE/source/fleet.git" rev-parse refs/heads/fleet-local)
  [ "$published_sha" = "$FLEET_SHA" ] || fail 'Local Git source did not publish the selected revision.'
}

local_build_image() {
  local build_directory
  build_directory=$(mktemp -d "$FLEET_STATE/build.XXXXXX")
  git archive "$FLEET_SHA" applications/load-harness | tar -x -C "$build_directory"
  if docker build --build-arg "APP_VERSION=$FLEET_TAG" \
    -t "localhost:5001/load-harness:$FLEET_TAG" "$build_directory/applications/load-harness"; then
    rm -rf "$build_directory"
  else
    rm -rf "$build_directory"
    return 1
  fi
  docker push "localhost:5001/load-harness:$FLEET_TAG"
}

local_configuration() {
  local traffic_endpoint=${1:-pending.local}
  kctl create configmap fleet-config -n flux-system \
    --from-literal=IMAGE_REGISTRY="$FLEET_REGISTRY:5000" \
    --from-literal=IMAGE_TAG="$FLEET_TAG" \
    --from-literal=TRAFFIC_PROVIDER=gatewayapi:v1 \
    --from-literal=TRAFFIC_ENDPOINT="$traffic_endpoint" \
    --from-literal=APP_HOSTNAME=localhost \
    --from-literal=RUNTIME_CONFIG_REVISION="$FLEET_SHA" \
    --dry-run=client -o yaml | kctl apply -f -
  kctl label configmap fleet-config -n flux-system reconcile.fluxcd.io/watch=Enabled --overwrite >/dev/null
}

local_secrets() {
  local secret filename namespace key credential
  for namespace in flux-system applications observability; do
    kctl create namespace "$namespace" --dry-run=client -o yaml | \
      kctl apply --server-side --field-manager=fleet-local-facade -f - >/dev/null
  done
  for secret in load-harness-api-key load-harness-secret-key grafana-admin-credentials; do
    case "$secret" in
      load-harness-api-key) filename=api-key; namespace=applications; key=api-key ;;
      load-harness-secret-key) filename=session-key; namespace=applications; key='secret-key' ;;
      grafana-admin-credentials) filename=grafana-password; namespace=observability; key=admin-password ;;
    esac
    if [ ! -f "$FLEET_STATE/$filename" ]; then
      openssl rand -hex 32 | tr -d '\r\n' > "$FLEET_STATE/$filename"
      chmod 600 "$FLEET_STATE/$filename"
    fi
    # Normalize credentials created by older facade versions without rotating them.
    credential=$(tr -d '\r\n' < "$FLEET_STATE/$filename")
    [[ "$credential" =~ ^[0-9a-f]{64}$ ]] || fail "Invalid cached credential: $filename" || return 1
    printf '%s' "$credential" > "$FLEET_STATE/$filename"
    if [ "$secret" = grafana-admin-credentials ]; then
      kctl create secret generic "$secret" -n "$namespace" \
        --from-literal=admin-user=admin --from-literal="$key=$credential" \
        --dry-run=client -o yaml | \
        kctl apply --server-side --field-manager=fleet-local-facade -f - >/dev/null
    else
      kctl create secret generic "$secret" -n "$namespace" \
        --from-literal="$key=$credential" --dry-run=client -o yaml | \
        kctl apply --server-side --field-manager=fleet-local-facade -f - >/dev/null
    fi
  done
}

local_calico() {
  local manifest checksum
  manifest="$FLEET_STATE/calico-v3.32.2.yaml"
  curl --fail --silent --show-error --location --retry 3 \
    https://raw.githubusercontent.com/projectcalico/calico/v3.32.2/manifests/calico.yaml -o "$manifest"
  checksum=$(openssl dgst -sha256 "$manifest" | awk '{print $NF}')
  [ "$checksum" = a8c828a06a87c629a282ebbc424895b77f3a030251993e41ea400a743675bb02 ] || fail 'Calico manifest checksum mismatch.' || return 1
  kctl apply --server-side -f "$manifest" >/dev/null
  kctl rollout status daemonset/calico-node -n kube-system --timeout=5m
  kctl wait --for=condition=Ready node --all --timeout=5m
}

local_start_services() {
  local node git_ip
  docker build -t "$FLEET_GIT_IMAGE" "$fleet_root/platform/local/git-server"
  if docker inspect "$FLEET_REGISTRY" >/dev/null 2>&1; then
    local_owned_container "$FLEET_REGISTRY"
    docker start "$FLEET_REGISTRY" >/dev/null
  else
    docker run -d --name "$FLEET_REGISTRY" --network kind \
      --label "io.infra-fleet.owner=$FLEET_OWNER" \
      -e OTEL_TRACES_EXPORTER=none \
      -p 127.0.0.1:5001:5000 -v "$FLEET_STATE/registry:/var/lib/registry" \
      "$FLEET_REGISTRY_IMAGE" >/dev/null
  fi
  for node in $(kind get nodes --name "$FLEET_CLUSTER"); do
    docker exec "$node" mkdir -p "/etc/containerd/certs.d/$FLEET_REGISTRY:5000"
    docker exec -i "$node" sh -c 'cat > /etc/containerd/certs.d/fleet-local-registry:5000/hosts.toml' <<'EOF'
server = "http://fleet-local-registry:5000"
[host."http://fleet-local-registry:5000"]
  capabilities = ["pull", "resolve"]
EOF
  done
  if docker inspect "$FLEET_GIT" >/dev/null 2>&1; then
    local_owned_container "$FLEET_GIT"
    if [ "$(docker inspect --format '{{.Image}}' "$FLEET_GIT")" != "$(docker image inspect --format '{{.Id}}' "$FLEET_GIT_IMAGE")" ]; then
      docker rm -f "$FLEET_GIT" >/dev/null
    fi
  fi
  if docker inspect "$FLEET_GIT" >/dev/null 2>&1; then
    docker start "$FLEET_GIT" >/dev/null
  else
    docker run -d --name "$FLEET_GIT" --network kind \
      --label "io.infra-fleet.owner=$FLEET_OWNER" \
      --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
      -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/srv/fleet.git \
      -v "$FLEET_STATE/source:/srv:ro" "$FLEET_GIT_IMAGE" >/dev/null
  fi
  sleep 1
  git_ip=$(docker inspect --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}' "$FLEET_GIT")
  [[ "$git_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'Missing local Git service address.' || return 1
  kctl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: fleet-local-git
  namespace: flux-system
spec:
  ports:
    - name: git
      port: 8080
      targetPort: 8080
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: fleet-local-git
  namespace: flux-system
  labels:
    kubernetes.io/service-name: fleet-local-git
addressType: IPv4
ports:
  - name: git
    protocol: TCP
    port: 8080
endpoints:
  - addresses: ["$git_ip"]
    conditions:
      ready: true
EOF
}

local_gateway_service() {
  kctl get service -n envoy-gateway-system \
    -l gateway.envoyproxy.io/owning-gateway-name=fleet \
    -o jsonpath='{.items[0].metadata.name}'
}

local_wait_gateway() {
  local deadline=$((SECONDS + 300))
  until kctl get gateway fleet -n envoy-gateway-system >/dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || fail 'Gateway was not created within 300s.' || return 1
    sleep 3
  done
  kctl wait --for=condition=Programmed gateway/fleet -n envoy-gateway-system --timeout=5m
}

local_up() {
  local_revision "$1"
  if local_cluster_exists; then
    local_existing_cluster
  else
    printf '%s\n' "$FLEET_OWNER" > "$FLEET_STATE/cluster-owned"
    kind create cluster --name "$FLEET_CLUSTER" --image "$FLEET_NODE_IMAGE" \
      --config "$fleet_root/platform/local/kind.yaml" --kubeconfig "$FLEET_STATE/kubeconfig"
  fi
  local_calico
  local_secrets
  local_publish_snapshot
  local_start_services
  local_build_image
  local_configuration
  fctl install --version=v2.7.5 --components=source-controller,kustomize-controller,helm-controller
  for controller in source-controller kustomize-controller helm-controller; do
    kctl rollout status deployment/"$controller" -n flux-system --timeout=5m
  done
  kctl apply -f "$fleet_root/platform/local/flux-source.yaml"
  fctl reconcile source git fleet-local --timeout=5m
  fctl reconcile kustomization fleet-root --timeout=5m
  kctl wait --for=condition=Ready kustomization/infrastructure -n flux-system --timeout=15m
  local_wait_gateway
  local_configuration "$(local_gateway_service).envoy-gateway-system"
  fctl reconcile kustomization applications --with-source --timeout=15m
  kctl wait --for=condition=Ready kustomization/policies -n flux-system --timeout=5m
  echo 'Local Kubernetes is ready. Use ./fleet access --profile local and ./fleet credentials --profile local.'
}

local_sync() {
  local_existing_cluster
  local_revision "$1"
  local_build_image
  local_publish_snapshot
  local_secrets
  local_configuration "$(local_gateway_service).envoy-gateway-system"
  fctl reconcile kustomization fleet-root --with-source --timeout=5m
  fctl reconcile kustomization infrastructure --timeout=15m
  local_wait_gateway
  fctl reconcile kustomization routing --timeout=15m
  fctl reconcile kustomization policies --timeout=15m
  fctl reconcile kustomization applications --timeout=15m
}

local_down() {
  if local_cluster_exists; then
    local_existing_cluster
    kind delete cluster --name "$FLEET_CLUSTER"
  fi
  for container in "$FLEET_GIT" "$FLEET_REGISTRY"; do
    if docker inspect "$container" >/dev/null 2>&1; then
      local_owned_container "$container"
      docker rm -f "$container" >/dev/null
    fi
  done
  echo 'Local cluster and its supporting containers stopped. Cached images and credentials retained.'
}

local_main() {
  local action=$1 revision=$2 service=$3
  local_prerequisites
  case "$action" in
    up) local_up "$revision" ;;
    sync) local_sync "$revision" ;;
    down) local_down ;;
    status)
      local_existing_cluster
      kctl get nodes
      kctl get kustomizations,gitrepositories -n flux-system
      kctl get helmreleases -A
      kctl get canaries -n applications ;;
    access)
      local_existing_cluster
      case "$service" in
        app) kctl port-forward -n envoy-gateway-system "service/$(local_gateway_service)" 8080:80 --address=127.0.0.1 ;;
        prometheus) kctl port-forward -n observability service/kube-prometheus-stack-prometheus 9090:9090 --address=127.0.0.1 ;;
        grafana) kctl port-forward -n observability service/kube-prometheus-stack-grafana 3000:80 --address=127.0.0.1 ;;
        *) fail 'Choose --service app, prometheus or grafana.' ;;
      esac ;;
    credentials)
      local_existing_cluster
      printf 'Application API key: '
      kctl get secret load-harness-api-key -n applications -o jsonpath='{.data.api-key}' | openssl base64 -d -A
      printf '\nGrafana user: admin\nGrafana password: '
      kctl get secret grafana-admin-credentials -n observability -o jsonpath='{.data.admin-password}' | openssl base64 -d -A
      printf '\n' ;;
    test) source "$fleet_root/scripts/fleet-profiles/test-local.sh"; test_local ;;
  esac
}
