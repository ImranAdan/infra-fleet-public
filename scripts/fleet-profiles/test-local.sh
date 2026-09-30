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
  local expected=$1 timeout=$2 phase applied deadline started=false
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    read -r applied phase <<< "$(test_canary_state)"
    if [ "$phase" = Progressing ]; then
      started=true
      # Remember every spec Flagger analysed for a test revision; restoration
      # must not accept a phase that still belongs to one of them.
      case " $FLEET_TEST_SPECS " in *" $applied "*) ;; *) FLEET_TEST_SPECS+=" $applied" ;; esac
    fi
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

# The canary's applied spec and phase, read together so they describe one moment.
test_canary_state() {
  kctl get canary "$APP_NAME" -n applications -o jsonpath='{.status.lastAppliedSpec} {.status.phase}'
}

# Wait for the original revision's canary to finish before testing: a Progressing
# seen afterwards then belongs to a test revision, whose spec restoration
# excludes. Right after `fleet sync` the original is often still being analysed.
test_wait_baseline() {
  local timeout=${1:-600} deadline applied phase
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    read -r applied phase <<< "$(test_canary_state)"
    case "$phase" in Initialized|Succeeded|Failed) return 0 ;; esac
    sleep 3
  done
  kctl describe canary "$APP_NAME" -n applications
  fail "Canary did not settle before testing within ${timeout}s."
}

# Wait until the canary is terminal on a spec that is not a test revision's. A
# terminal phase alone is not enough: restoration can begin from a test
# revision's stale Succeeded, and Flagger observes the restored Deployment
# asynchronously. The original spec's hash is not known up front: each local
# commit changes the Deployment, so it is identified by exclusion.
test_wait_restored() {
  local timeout=${1:-600} deadline applied phase
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    read -r applied phase <<< "$(test_canary_state)"
    case " $FLEET_TEST_SPECS " in
      *" $applied "*) ;;
      *) case "$phase" in Initialized|Succeeded) return 0 ;; esac ;;
    esac
    sleep 3
  done
  kctl describe canary "$APP_NAME" -n applications
  fail "Canary did not settle on the original revision within ${timeout}s."
}

test_publish_snapshot() {
  local snapshot=$1
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch --quiet --force "$snapshot" HEAD:refs/heads/fleet-local
  fctl reconcile kustomization applications --with-source --timeout=5m
}

# The small readiness contract test overrides the timeout; production uses the default.
# shellcheck disable=SC2120
test_wait_application() {
  local timeout=${1:-120} deadline
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if kctl exec -n flux-system deployment/flagger-loadtester -- \
      curl --fail --silent --max-time 10 \
      "http://$APP_NAME-primary.applications:$APP_PORT$APP_HEALTH_PATH" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  fail "$APP_NAME-primary did not become healthy within ${timeout}s."
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

test_dashboard_action() {
  local app=$1 action=$2
  kctl exec -n fleet-control deployment/control-plane -- python3 -c '
import sys, urllib.request
request = urllib.request.Request(
    f"http://127.0.0.1:8080/api/apps/{sys.argv[1]}/{sys.argv[2]}",
    method="POST",
    headers={"Host": "localhost:9000", "X-Fleet-Action": "1"},
)
with urllib.request.urlopen(request, timeout=15) as response:
    assert response.status == 202
' "$app" "$action" >/dev/null
}

test_dashboard_proxy() {
  local app=$1 health_path=$2
  kctl exec -n fleet-control deployment/control-plane -- python3 -c '
import sys, urllib.request
request = urllib.request.Request(
    "http://127.0.0.1:8080" + sys.argv[2],
    headers={"Host": sys.argv[1] + ".localhost:9000"},
)
with urllib.request.urlopen(request, timeout=15) as response:
    assert 200 <= response.status < 300
' "$app" "$health_path" >/dev/null
}

test_wait_dashboard_app() {
  local app=$1 health_path=$2 timeout=${3:-180} deadline
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if test_dashboard_proxy "$app" "$health_path" 2>/dev/null; then return 0; fi
    sleep 3
  done
  kctl get kustomizations -n flux-system "app-$app" "app-$app-platform" -o wide >&2 || true
  kctl get canary,deployment -n applications >&2 || true
  fail "$app did not become reachable through the dashboard within ${timeout}s."
}

test_control_plane() {
  local launch_app contract app_port health_path load_path
  # Go-template variables are intentionally literal shell input.
  # shellcheck disable=SC2016
  launch_app=$(kctl get configmap fleet-catalog -n flux-system \
    -o go-template='{{range $key, $value := .data}}{{printf "%s\n" $key}}{{end}}' | \
    awk -v selected="$APP_NAME" '$0 != selected && !found { print; found = 1 }')
  [ -n "$launch_app" ] || fail 'The dashboard acceptance needs another app contract.' || return 1
  contract=$(kctl get configmap fleet-catalog -n flux-system -o "jsonpath={.data['$launch_app']}")
  app_port=$(awk '$1 == "APP_PORT:" { sub(/^[^:]*:[ \t]*/, ""); gsub(/^"|"$/, ""); print; exit }' <<< "$contract")
  health_path=$(awk '$1 == "APP_HEALTH_PATH:" { sub(/^[^:]*:[ \t]*/, ""); gsub(/^"|"$/, ""); print; exit }' <<< "$contract")
  load_path=$(awk '$1 == "APP_LOAD_PATH:" { sub(/^[^:]*:[ \t]*/, ""); gsub(/^"|"$/, ""); print; exit }' <<< "$contract")
  [ -n "$app_port" ] && [ -n "$health_path" ] && [ -n "$load_path" ] ||
    fail "$launch_app has an incomplete runtime contract." || return 1

  echo 'Checking admission rejects a dashboard launch with an arbitrary image.'
  if kctl create --dry-run=server \
    --as=system:serviceaccount:fleet-control:control-plane -f - \
    > "$FLEET_STATE/admission.log" 2>&1 <<EOF
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app-$launch_app
  namespace: flux-system
  labels:
    infra-fleet.io/launched-app: $launch_app
spec:
  interval: 1m
  path: ./k8s/applications/$launch_app
  prune: true
  wait: false
  timeout: 10m
  serviceAccountName: app-deployer
  sourceRef:
    kind: GitRepository
    name: fleet-local
  images:
    - name: app
      newName: docker.io/library/busybox
      newTag: latest
  postBuild:
    substitute:
      APP_NAME: $launch_app
      APP_PORT: "$app_port"
      APP_HEALTH_PATH: "$health_path"
      APP_LOAD_PATH: "$load_path"
      APP_HOSTNAME: $launch_app.apps.localhost
    substituteFrom:
      - kind: ConfigMap
        name: fleet-config
EOF
  then
    fail 'The dashboard identity could override a launched app image.'; return 1
  fi
  grep -q control-plane-launches "$FLEET_STATE/admission.log" || {
    cat "$FLEET_STATE/admission.log" >&2
    fail 'The unsafe dashboard launch failed outside its admission boundary.'; return 1
  }

  echo "Checking the dashboard launches and removes $launch_app through Flux."
  FLEET_TEST_LAUNCHED=$launch_app
  test_dashboard_action "$launch_app" launch
  kctl wait --for=condition=Ready -n flux-system \
    "kustomization/app-$launch_app" "kustomization/app-$launch_app-platform" --timeout=3m
  test_wait_dashboard_app "$launch_app" "$health_path" 180
  test_dashboard_action "$launch_app" stop
  kctl wait --for=delete -n flux-system \
    "kustomization/app-$launch_app" "kustomization/app-$launch_app-platform" --timeout=3m
  if kctl get canary "$launch_app" -n applications >/dev/null 2>&1; then
    fail "$launch_app remained after the dashboard stopped it."; return 1
  fi
  FLEET_TEST_LAUNCHED=

  echo 'Checking other pods cannot drive the dashboard control API.'
  [ "$(kctl get --raw '/api/v1/namespaces/fleet-control/services/control-plane:80/proxy/healthz')" = ok ]
  if kctl exec -n flux-system deployment/flagger-loadtester -- \
    curl --fail --silent --connect-timeout 3 --max-time 5 \
    http://control-plane.fleet-control/api/apps >/dev/null 2>&1; then
    fail 'A pod outside fleet-control reached the dashboard.'; return 1
  fi
}

test_restore_snapshot() {
  local test_result=$?
  trap - EXIT INT TERM
  if [ -n "${FLEET_TEST_LAUNCHED:-}" ]; then
    test_dashboard_action "$FLEET_TEST_LAUNCHED" stop || test_result=1
  fi
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch --quiet --force "$fleet_root" "$FLEET_TEST_ORIGINAL:refs/heads/fleet-local" || test_result=1
  if fctl reconcile kustomization applications --with-source --timeout=5m; then
    test_wait_restored 600 || test_result=1
  else
    test_result=1
  fi
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
  test_wait_baseline 600 || return 1
  FLEET_TEST_SPECS=""
  FLEET_TEST_LAUNCHED=""
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
  # shellcheck disable=SC2119
  test_wait_application
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

  test_control_plane

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
  echo 'Local acceptance passed: drift, admission, monitoring, network isolation, on-demand apps, promotion and rollback.'
}
