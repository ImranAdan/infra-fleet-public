#!/usr/bin/env bash
# Experiments are confined to this facade's local Git source and cluster.
fleet_root=${fleet_root:?Local acceptance requires the fleet root}

# The deployed app contract; the test names no app of its own.
test_app() { kctl get configmap fleet-app -n flux-system -o jsonpath="{.data.$1}"; }

# Add a strategic-merge patch for the app Deployment to the local overlay of
# the test snapshot. Merging leaves the app's own manifests untouched.
test_patch_app() {
  local overlay="$FLEET_TEST_SNAPSHOT/k8s/profiles/local/applications/kustomization.yaml"
  {
    printf '  - target:\n      kind: Deployment\n      name: %s\n    patch: |-\n' "$APP_NAME"
    printf '      apiVersion: apps/v1\n      kind: Deployment\n      metadata:\n        name: %s\n' "$APP_NAME"
    printf '%s\n' "$1" | sed 's/^/      /'
  } >> "$overlay"
  git -C "$FLEET_TEST_SNAPSHOT" add k8s/profiles/local/applications/kustomization.yaml
  git -C "$FLEET_TEST_SNAPSHOT" commit --quiet -m "$2"
}

test_wait_phase() {
  local expected=$1 timeout=$2 phase deadline started=false
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase=$(kctl get canary "$APP_NAME" -n applications -o jsonpath='{.status.phase}')
    if [ "$phase" = Progressing ]; then started=true; fi
    if [ "$started" = true ] && [ "$phase" = "$expected" ]; then return 0; fi
    if [ "$started" = true ] && [ "$phase" = Failed ] && [ "$expected" != Failed ]; then
      kctl describe canary "$APP_NAME" -n applications
      fail "Canary failed while waiting for $expected."; return 1
    fi
    sleep 3
  done
  kctl describe canary "$APP_NAME" -n applications
  fail "Canary did not reach $expected within ${timeout}s."
}

test_publish_snapshot() {
  local snapshot=$1
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch --quiet --force "$snapshot" HEAD:refs/heads/fleet-local
  fctl reconcile kustomization applications --with-source --timeout=5m
}

test_wait_monitoring() {
  local deadline=$((SECONDS + 120))
  while [ "$SECONDS" -lt "$deadline" ]; do
    # Platform monitoring covers any app: its container is visible to Prometheus.
    if kctl exec -n flux-system deployment/flagger-loadtester -- \
      curl --fail --silent --max-time 10 --get \
      --data-urlencode "query=count(container_cpu_usage_seconds_total{namespace=\"applications\",container=\"$APP_NAME\"}) > bool 0" \
      'http://kube-prometheus-stack-prometheus.observability:9090/api/v1/query' \
      > "$FLEET_STATE/monitoring.json" && \
      grep -Eq '"value":\[[^]]*,"1"\]' "$FLEET_STATE/monitoring.json"; then
      return 0
    fi
    sleep 3
  done
  cat "$FLEET_STATE/monitoring.json" >&2
  fail 'Prometheus did not report the application container within 120s.'
}

test_restore_snapshot() {
  local test_result=$?
  trap - EXIT INT TERM
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch --quiet --force "$fleet_root" "$FLEET_TEST_ORIGINAL:refs/heads/fleet-local" || test_result=1
  fctl reconcile kustomization applications --with-source --timeout=5m || test_result=1
  kctl delete namespace fleet-test --ignore-not-found >/dev/null || test_result=1
  rm -rf "$FLEET_TEST_SNAPSHOT"
  exit "$test_result"
}

test_local() {
  local_existing_cluster
  APP_NAME=$(test_app APP_NAME)
  APP_PORT=$(test_app APP_PORT)
  APP_HEALTH_PATH=$(test_app APP_HEALTH_PATH)
  APP_FAULT_ENV=$(test_app APP_FAULT_ENV)
  [ -n "$APP_NAME" ] && [ -n "$APP_PORT" ] && [ -n "$APP_HEALTH_PATH" ] &&
    [[ "$APP_FAULT_ENV" == ?*=* ]] || fail 'The deployed fleet-app contract is incomplete.' || return 1
  FLEET_TEST_ORIGINAL=$(kctl get gitrepository fleet-local -n flux-system -o jsonpath='{.status.artifact.revision}')
  FLEET_TEST_ORIGINAL=${FLEET_TEST_ORIGINAL##*:}
  [[ "$FLEET_TEST_ORIGINAL" =~ ^[0-9a-f]{40}$ ]] || fail 'Cannot verify the original local source revision.' || return 1
  FLEET_TEST_SNAPSHOT=$(mktemp -d "$FLEET_STATE/test-snapshot.XXXXXX")
  trap test_restore_snapshot EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  echo 'Checking Flux restores declared metadata drift.'
  kctl label deployment "$APP_NAME" -n applications managed-by=manual --overwrite >/dev/null
  fctl reconcile kustomization applications --timeout=5m
  [ "$(kctl get deployment "$APP_NAME" -n applications -o jsonpath='{.metadata.labels.managed-by}')" = flux ]

  echo 'Checking Kyverno rejects unsafe rollout and registry requests.'
  for fixture in bad-rollout bad-registry bad-registry-sidecar bad-latest-sidecar; do
    if kctl apply --dry-run=server -f "$fleet_root/tests/profiles/admission/$fixture.yaml" > "$FLEET_STATE/admission.log" 2>&1; then
      fail "Kyverno accepted $fixture."; return 1
    fi
    case "$fixture" in
      bad-rollout) grep -q require-rollout-capacity "$FLEET_STATE/admission.log" ;;
      bad-registry|bad-registry-sidecar) grep -q require-local-images "$FLEET_STATE/admission.log" ;;
      bad-latest-sidecar) grep -q block-latest-tag "$FLEET_STATE/admission.log" ;;
    esac
  done

  echo 'Checking application monitoring and network isolation.'
  kctl exec -n flux-system deployment/flagger-loadtester -- \
    curl --fail --silent --max-time 10 "http://$APP_NAME-primary.applications:$APP_PORT$APP_HEALTH_PATH" >/dev/null
  test_wait_monitoring
  kctl create namespace fleet-test --dry-run=client -o yaml | kctl apply -f - >/dev/null
  local probe_image
  probe_image=$(kctl get deployment flagger-loadtester -n flux-system -o jsonpath='{.spec.template.spec.containers[0].image}')
  # $result is evaluated inside the probe pod; the app URL is expanded here.
  # shellcheck disable=SC2016
  kctl run fleet-test-network -n fleet-test --restart=Never --image="$probe_image" --command -- \
    sh -c 'curl -fsS --max-time 10 http://kube-prometheus-stack-prometheus.observability:9090/-/ready >/dev/null || exit 2; curl -fsS --connect-timeout 3 --max-time 5 "$0" >/dev/null; result=$?; [ "$result" -eq 28 ]' \
    "http://$APP_NAME-primary.applications:$APP_PORT$APP_HEALTH_PATH" >/dev/null
  kctl wait pod/fleet-test-network -n fleet-test --for=jsonpath='{.status.phase}'=Succeeded --timeout=2m

  echo 'Checking a Git-delivered revision is promoted by Flagger.'
  git clone --quiet --branch fleet-local --single-branch "$FLEET_STATE/source/fleet.git" "$FLEET_TEST_SNAPSHOT"
  git -C "$FLEET_TEST_SNAPSHOT" config user.name 'Fleet local acceptance'
  git -C "$FLEET_TEST_SNAPSHOT" config user.email 'fleet-local@example.invalid'
  test_patch_app 'spec:
  template:
    metadata:
      annotations:
        infra-fleet.io/local-acceptance: promotion' 'test: exercise local canary promotion'
  test_publish_snapshot "$FLEET_TEST_SNAPSHOT"
  test_wait_phase Succeeded 600
  [ "$(kctl get deployment "$APP_NAME-primary" -n applications -o jsonpath='{.spec.template.metadata.annotations.infra-fleet\.io/local-acceptance}')" = promotion ]

  echo 'Checking a Git-delivered faulty revision rolls back automatically.'
  # The app's declared fault switch, merged into its container by name.
  test_patch_app "spec:
  template:
    spec:
      containers:
        - name: $APP_NAME
          env:
            - name: ${APP_FAULT_ENV%%=*}
              value: \"${APP_FAULT_ENV#*=}\"" 'test: exercise local canary rollback'
  test_publish_snapshot "$FLEET_TEST_SNAPSHOT"
  test_wait_phase Failed 600
  [ "$(kctl get deployment "$APP_NAME-primary" -n applications -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"${APP_FAULT_ENV%%=*}\")].value}")" != "${APP_FAULT_ENV#*=}" ]
  echo 'Local acceptance passed: drift, admission, monitoring, network isolation, promotion and rollback.'
}
