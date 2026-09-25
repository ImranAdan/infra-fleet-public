---
name: verify-fleet
description: Drive the local Infra Fleet (kind + Flux + Flagger + Envoy Gateway + Prometheus/Grafana) the way an operator does and capture evidence that a change works. Use before claiming a fleet change works, when reviewing a platform or app change, or when anything on the local cluster looks off. Covers the app contract and swap, canary promotion and rollback, gateway golden signals and dashboards, and the GitOps, admission and isolation guardrails.
---

# Verify the fleet

Prove behavior on the running local cluster, not in a render or a unit test.
A render proves the manifests; only a live drive proves the platform. Read
[`features/README.md`](features/README.md) before driving, then use the
matching feature file as the recipe.

Adapted from the `create-verification-skill` and `maintain-verification-skill`
method in [pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT).

## Launch

```bash
./fleet setup --profile local       # once per machine: pinned kind, kubectl, flux
./fleet up --profile local          # creates or repairs the cluster; ~10 min cold
./fleet sync --profile local        # deploy the committed HEAD to a running cluster
```

`up` and `sync` deploy **committed** revisions only; commit first. Ready means
`up` or `sync` exits 0 and the doctor passes. Use only the fleet's own
kubeconfig, `$(git rev-parse --git-common-dir)/fleet/local/kubeconfig`, never
the default context: it may point at a deleted cluster. One cluster exists per
checkout; there is no second instance to run side by side, so never drive it
while another agent is deploying or testing on it. Ask first.

## Doctor

```bash
.claude/skills/verify-fleet/doctor.sh
```

Read-only; exits 1 on any `FAIL`. Run it before the first drive, after any
failed drive, and whenever something surprises you. Each check encodes a
failure met in practice:

- Docker restarted: the kind node returns but `fleet-local-git` and
  `fleet-local-registry` do not (`./fleet up` restores them).
- Flux layers on different revisions, or `applications` suspended: an
  interrupted sync (`./fleet sync` or `up` clears it).
- The cluster runs a different app than the checkout selects.
- A canary mid-analysis: traffic you send becomes part of its gates, and its
  pods churn under you. Wait for `Initialized`, `Succeeded` or `Failed`.
- Node CPU over 70%: latency results will mislead. Once, Kyverno's reports
  controller looped and added hundreds of milliseconds to every request.

## Drive

Prefer in-cluster paths over port-forwards, which drop whenever a pod behind
them is replaced:

- **Prometheus:** `kubectl get --raw "/api/v1/namespaces/observability/services/kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=<urlencoded>"`.
- **The app through the gateway:** `kubectl exec -n flux-system deploy/flagger-loadtester -- hey -host localhost http://<gateway-service>.envoy-gateway-system/<path>`.
  `hey` ignores `-H 'Host: …'`; only `-host` reaches the app's route. The
  gateway service is `kubectl get svc -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=fleet`.
- **The app directly:** `kubectl exec -n <ns> <pod> -- …` from inside the pod,
  to separate app latency from network latency.
- **Humans in a browser:** `./fleet access --profile local --service app|grafana|prometheus`
  and `./fleet credentials --profile local`.

Scripted drives shipped with this skill:

- `.claude/skills/verify-fleet/doctor.sh`: health, above.
- `.claude/skills/verify-fleet/ground-truth.sh [N]`: sends exactly N requests
  through the gateway and requires Prometheus's raw Envoy counter to rise by
  exactly N. Proves the golden signals count what really happened.
- `./fleet test --profile local`: the full acceptance cycle (drift, admission,
  monitoring, isolation, promotion, rollback) for whichever app is selected.

## Evidence

Evidence lives in `$(git rev-parse --git-common-dir)/fleet/verify/<run>/`,
outside the working tree, and survives cleanup. The standard:

- Exercise the real path: through the gateway, through Flux from Git, with the
  real image. Never patch a live object to fake a state Git did not declare.
- Compare against ground truth you control: a count you sent, a revision you
  committed, a fault you injected. A dashboard with data is not proof its
  numbers are right; one showed half the real traffic until checked this way.
- Capture the action and the resulting state: the command, its output and exit
  code, then a second, read-only view (a Prometheus query, `kubectl get`,
  canary events).
- Say `inconclusive` when a check could not run. Never report a path as
  verified through a different one.

## Cleanup

Kill only what you started: your own port-forwards and background drives.
Leave the cluster running unless you created it for this run; then
`./fleet down --profile local`, which keeps cached tools, images and
credentials. `./fleet test` restores the deployed revision itself. Evidence
stays.

## Maintain

The map rots as the fleet changes. After changing a user-visible surface
(a `./fleet` action, the app contract, canary gates, a dashboard, a policy),
re-drive the affected feature and update its file in the same change. A
periodic pass reads each feature file against the source, drives every feature
live once, and ends `clean`, `changed` (proven corrections, confined to this
directory, kept local and proposed as a pull request for the owner to approve)
or `blocked` (name the blocker). Never edit product code in that pass: a behavior
the map describes that the fleet no longer has is either map drift (fix the
map) or a regression (report it).
