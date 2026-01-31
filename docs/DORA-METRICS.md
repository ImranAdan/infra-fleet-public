# DORA Metrics

This document describes how DORA metrics are collected and visualized in infra-fleet.

## Goals

- Track deployment frequency, lead time, change failure rate, and MTTR.
- Use existing GitHub Actions, Flux, and Flagger signals.
- Keep the system lightweight and suitable for an ephemeral stack.

## Data Sources

We collect metrics from three sources:

1) **Workflow runs** (GitHub Actions)
   - `rebuild-stack.yml`
   - `infra-apply.yml`
   - `load-harness-ci.yml` (tag releases)

2) **Flux GitOps**
   - `kustomization/applications` status and revision.

3) **Flagger**
   - Canary phase (used as rollback signal).

## Architecture

```text
GitHub Actions ──push──> Pushgateway ──scrape──> Prometheus ──dashboards──> Grafana
         │
         └──> Flux/Flagger queries via kubectl
```

### Components

- **Pushgateway**: `k8s/infrastructure/observability/pushgateway.yaml`
- **Metrics workflow**: `.github/workflows/dora-metrics.yml`
- **Grafana dashboard**: `applications/load-harness/monitoring/dora-metrics.json`

## Metric Definitions

### Deployment Frequency

- Workflow deploys: count `dora_workflow_deploy_timestamp{status="success"}` per window.
- Flux deploys: count `dora_flux_applied_timestamp` per window.

### Lead Time for Changes

- Workflow lead time: `dora_workflow_lead_time_seconds`
  - Computed from commit timestamp → workflow completion.
- Flux lead time: `dora_flux_lead_time_seconds`
  - Computed from Git revision timestamp → Flux applied time.

### Change Failure Rate

- Workflow failures: `dora_workflow_deploy_timestamp{status="failure"}`
- Flagger rollbacks: `dora_flagger_canary_timestamp{phase="Failed"}`

### MTTR (heuristic)

Measure time between a failure signal and the next success of the same source:

- Workflow: failed deploy → next successful deploy.
- Flagger: `Failed` phase → next successful deploy or Flux revision.

## Metrics Emitted

### Workflow Metrics

- `dora_workflow_deploy_event{source,status,sha,ref} 1`
- `dora_workflow_deploy_timestamp{source,status,sha} <unix>`
- `dora_workflow_lead_time_seconds{source,status,sha} <seconds>`

### Flux Metrics

- `dora_flux_applied_timestamp{revision,ready} <unix>`
- `dora_flux_ready{revision,ready} 1`
- `dora_flux_lead_time_seconds{revision} <seconds>`

### Flagger Metrics

- `dora_flagger_canary_phase{canary,phase} 1`
- `dora_flagger_canary_timestamp{canary,phase} <unix>`

## Workflow Behavior

`dora-metrics.yml` has two jobs:

- **workflow-metrics**: runs on `workflow_run` for rebuild/infra/app workflows.
- **cluster-metrics**: runs on `schedule` and manual dispatch; queries Flux/Flagger.

Both jobs:

- Use OIDC to access EKS.
- Skip when the cluster does not exist.

## Dashboard

Grafana dashboard file:

- `applications/load-harness/monitoring/dora-metrics.json`

Local dev import:

- `applications/load-harness/local-dev/setup-grafana.sh`
- `ops/import-grafana-dashboard.sh`

## Local Testing

1) Start local stack:

```bash
./applications/load-harness/local-dev/dev.sh up-full
```

2) Import dashboards:

```bash
./applications/load-harness/local-dev/dev.sh setup
```

3) View Grafana:

```text
http://localhost:3000 (admin/admin)
```

## Production Testing

Trigger a run:

```bash
gh workflow run dora-metrics.yml
```

Verify metrics:

```bash
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090
curl -s "http://localhost:9090/api/v1/query?query=dora_workflow_deploy_event"
```

## Troubleshooting

- Flagger rollback spikes or missing canary metrics usually mean traffic did not
  pass through the NGINX ingress. Ensure load tests set the `Host` header and
  target the ingress service (see `k8s/applications/load-harness/canary.yaml`).

## Known Limitations

- Metrics are **ephemeral** with the stack; no long-term retention yet.
- Workflow metrics only appear after a workflow completes.
- Flux lead time depends on commit availability in GitHub.

## Future Enhancements

- Add retention via remote Prometheus storage.
- Parameterize cluster name for multi-env metrics.
- Add explicit MTTR panels in Grafana.
