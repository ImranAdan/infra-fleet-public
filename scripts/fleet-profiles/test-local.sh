#!/usr/bin/env bash
# Experiments are confined to this facade's local Git source and cluster.

test_wait_phase() {
  local expected=$1 timeout=$2 phase deadline
  deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase=$(kctl get canary load-harness -n applications -o jsonpath='{.status.phase}')
    if [ "$phase" = "$expected" ]; then return 0; fi
    if [ "$phase" = Failed ] && [ "$expected" != Failed ]; then
      kctl describe canary load-harness -n applications
      fail "Canary failed while waiting for $expected."; return 1
    fi
    sleep 3
  done
  kctl describe canary load-harness -n applications
  fail "Canary did not reach $expected within ${timeout}s."
}

test_publish_snapshot() {
  local snapshot=$1
  git --git-dir="$FLEET_STATE/source/fleet.git" fetch --quiet --force "$snapshot" HEAD:refs/heads/fleet-local
  fctl reconcile kustomization applications --with-source --timeout=5m
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
  FLEET_TEST_ORIGINAL=$(kctl get gitrepository fleet-local -n flux-system -o jsonpath='{.status.artifact.revision}')
  FLEET_TEST_ORIGINAL=${FLEET_TEST_ORIGINAL##*:}
  [[ "$FLEET_TEST_ORIGINAL" =~ ^[0-9a-f]{40}$ ]] || fail 'Cannot verify the original local source revision.' || return 1
  FLEET_TEST_SNAPSHOT=$(mktemp -d "$FLEET_STATE/test-snapshot.XXXXXX")
  trap test_restore_snapshot EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  echo 'Checking Flux restores declared metadata drift.'
  kctl label deployment load-harness -n applications managed-by=manual --overwrite >/dev/null
  fctl reconcile kustomization applications --timeout=5m
  [ "$(kctl get deployment load-harness -n applications -o jsonpath='{.metadata.labels.managed-by}')" = flux ]

  echo 'Checking Kyverno rejects unsafe rollout and registry requests.'
  for fixture in bad-rollout bad-registry; do
    if kctl apply --dry-run=server -f "$fleet_root/tests/profiles/admission/$fixture.yaml" > "$FLEET_STATE/admission.log" 2>&1; then
      fail "Kyverno accepted $fixture."; return 1
    fi
    case "$fixture" in
      bad-rollout) grep -q require-rollout-capacity "$FLEET_STATE/admission.log" ;;
      bad-registry) grep -q require-local-images "$FLEET_STATE/admission.log" ;;
    esac
  done

  echo 'Checking application monitoring and network isolation.'
  kctl exec -n flux-system deployment/flagger-loadtester -- \
    curl --fail --silent --max-time 10 http://load-harness-primary.applications:5000/health >/dev/null
  kctl exec -n flux-system deployment/flagger-loadtester -- \
    curl --fail --silent --max-time 10 \
    'http://kube-prometheus-stack-prometheus.observability:9090/api/v1/query?query=up%7Bnamespace%3D%22applications%22%7D' > "$FLEET_STATE/monitoring.json"
  grep -Eq '"value":\[[^]]*,"1"\]' "$FLEET_STATE/monitoring.json"
  kctl create namespace fleet-test --dry-run=client -o yaml | kctl apply -f - >/dev/null
  local probe_image
  probe_image=$(kctl get deployment flagger-loadtester -n flux-system -o jsonpath='{.spec.template.spec.containers[0].image}')
  kctl run fleet-test-network -n fleet-test --restart=Never --image="$probe_image" --command -- \
    sh -c 'curl -fsS --max-time 10 http://kube-prometheus-stack-prometheus.observability:9090/-/ready >/dev/null || exit 2; curl -fsS --connect-timeout 3 --max-time 5 http://load-harness-primary.applications:5000/health >/dev/null; result=$?; [ "$result" -eq 28 ]' >/dev/null
  kctl wait pod/fleet-test-network -n fleet-test --for=jsonpath='{.status.phase}'=Succeeded --timeout=2m

  echo 'Checking a Git-delivered revision is promoted by Flagger.'
  git clone --quiet --branch fleet-local --single-branch "$FLEET_STATE/source/fleet.git" "$FLEET_TEST_SNAPSHOT"
  git -C "$FLEET_TEST_SNAPSHOT" config user.name 'Fleet local acceptance'
  git -C "$FLEET_TEST_SNAPSHOT" config user.email 'fleet-local@example.invalid'
  sed '/annotations:/a\
        infra-fleet.io/local-acceptance: promotion
  ' "$FLEET_TEST_SNAPSHOT/k8s/applications/load-harness/deployment.yaml" > "$FLEET_STATE/test-deployment.yaml"
  mv "$FLEET_STATE/test-deployment.yaml" "$FLEET_TEST_SNAPSHOT/k8s/applications/load-harness/deployment.yaml"
  git -C "$FLEET_TEST_SNAPSHOT" add k8s/applications/load-harness/deployment.yaml
  git -C "$FLEET_TEST_SNAPSHOT" commit --quiet -m 'test: exercise local canary promotion'
  test_publish_snapshot "$FLEET_TEST_SNAPSHOT"
  test_wait_phase Succeeded 600
  [ "$(kctl get deployment load-harness-primary -n applications -o jsonpath='{.spec.template.metadata.annotations.infra-fleet\.io/local-acceptance}')" = promotion ]

  echo 'Checking a Git-delivered faulty revision rolls back automatically.'
  sed 's/value: "0.0"/value: "1.0"/' "$FLEET_TEST_SNAPSHOT/k8s/applications/load-harness/deployment.yaml" > "$FLEET_STATE/test-deployment.yaml"
  mv "$FLEET_STATE/test-deployment.yaml" "$FLEET_TEST_SNAPSHOT/k8s/applications/load-harness/deployment.yaml"
  git -C "$FLEET_TEST_SNAPSHOT" add k8s/applications/load-harness/deployment.yaml
  git -C "$FLEET_TEST_SNAPSHOT" commit --quiet -m 'test: exercise local canary rollback'
  test_publish_snapshot "$FLEET_TEST_SNAPSHOT"
  test_wait_phase Failed 600
  [ "$(kctl get deployment load-harness-primary -n applications -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="FAIL_RATE")].value}')" = 0.0 ]
  echo 'Local acceptance passed: drift, admission, monitoring, network isolation, promotion and rollback.'
}
