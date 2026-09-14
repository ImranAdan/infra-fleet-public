# Application Roadmap — Load Harness

A Python Flask synthetic workload service designed to stress the EKS cluster,
exercise HPA, validate the current NGINX/NLB ingress path, and provide observable
CPU and memory load.

> The community NGINX ingress controller is retired. This application remains
> useful locally and by port-forward; treat the cluster ingress as a private
> preview until the Gateway API migration is live-cycle tested.

## Purpose

This application provides a repeatable, controlled workload to validate:

- NLB → NGINX ingress → EKS behavior
- Application performance under load
- Resource limits and pod behavior
- Horizontal Pod Autoscaler (HPA) capabilities
- Cost modeling (CPU-seconds → cost-per-request)

The application is intentionally simple, predictable, and controllable.

## Cluster Assumptions

This project assumes:

```hcl
eks_managed_node_groups = {
  default = {
    instance_types = ["t3.large"]
    capacity_type  = "SPOT"
    desired_size   = 1
    min_size       = 1
    max_size       = 2
  }
}
```

Notes:

- With `min=1`, `max=2`, autoscaling is possible but limited.
- Real autoscaling tests require Cluster Autoscaler or Karpenter.
- The cluster already runs core system pods (kube-system, flux, observability).
- The NGINX ingress Service provisions an AWS NLB through AWS Load Balancer
  Controller.

## High-Level Architecture

```
User → NLB → NGINX Ingress → Service → Pods (Flask/Gunicorn)
                         |
                         └── /metrics → Prometheus → Grafana
```

Components:

- Flask application with Gunicorn WSGI server
- Prometheus metrics via `prometheus-flask-exporter`
- Configurable CPU and memory load endpoints
- Non-blocking sustained load with multiprocessing
- Health & readiness probes
- OpenAPI/Swagger documentation
- Multi-stage Docker image for EKS deployment

## Endpoints

Verified against `src/load_harness/load_harness_service.py` and
`src/load_harness/constants.py`.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Application info |
| `/health` | GET | Liveness check |
| `/ready` | GET | Readiness check |
| `/version` | GET | Build version, injected as `APP_VERSION` |
| `/system/info` | GET | Host CPU and memory as seen by the pod |
| `/metrics` | GET | Prometheus metrics, via `prometheus-flask-exporter` |
| `/load/cpu` | POST | Start CPU load in background workers. Returns immediately |
| `/load/cpu/status` | GET | Status of the running CPU job |
| `/load/cpu/stop` | POST | Stop CPU workers |
| `/load/cpu/work` | POST | **Blocking** CPU work. Occupies a worker, so load balances across pods |
| `/load/memory` | POST | Start memory load in a background worker. Returns immediately |
| `/load/memory/status` | GET | Status of the running memory job |
| `/load/memory/stop` | POST | Stop the memory worker |
| `/load/memory/sync` | POST | Legacy blocking memory load |
| `/apidocs` | GET | Interactive Swagger UI |
| `/apispec.json` | GET | OpenAPI specification |

The dashboard is mounted under `/ui` and adds `/ui/`, `/ui/login`,
`/ui/logout`, `/ui/api/system-info` and several `/ui/partials/*` routes used by
HTMX. The prefix comes from `url_prefix="/ui"` on the blueprint in
`src/load_harness/dashboard/routes.py`.

### POST /load/cpu — background CPU load

```json
{
  "cores": 1,
  "duration_seconds": 60,
  "intensity": 5
}
```

| Field | Range | Default |
|-------|-------|---------|
| `cores` | 1-16 | 1 |
| `duration_seconds` | 10-900 | 60 |
| `intensity` | 1-10 | 5 |

Returns immediately with a job id. Health probes stay responsive, which is what
makes this safe to run against a pod that Kubernetes is also monitoring.

### POST /load/cpu/work — blocking CPU work

```json
{
  "iterations": 100000
}
```

`iterations`: 1,000-10,000,000, default 100,000.

Unlike `/load/cpu`, this occupies the worker until it finishes. That is the
point: it is what the dashboard's distributed test uses to spread load across
pods rather than concentrating it in one.

### POST /load/memory — background memory load

```json
{
  "size_mb": 50,
  "duration_seconds": 30
}
```

| Field | Range | Default |
|-------|-------|---------|
| `size_mb` | 1-2048 | 50 |
| `duration_seconds` | 5-300 | 30 |

`/load/memory/sync` is the older blocking form, taking `size_mb` and
`duration_ms` (1-120,000, default 1,000).

## Metrics Exposed

Via `prometheus-flask-exporter`:

- `flask_http_request_total` — Request count by endpoint and status
- `flask_http_request_duration_seconds` — Request latency histogram
- `process_cpu_seconds_total` — Process CPU time
- `process_resident_memory_bytes` — Process memory usage

## Dockerfile

Multi-stage build. Rather than reproduce it here and let the copy drift, see
[`../Dockerfile`](../Dockerfile) - it is the source of truth. The properties
worth knowing:

- **Two stages.** Dependencies are built in the builder and only
  `/root/.local` is copied forward, so build tools never reach the runtime
  image.
- **No package installer at runtime.** `pip`, `setuptools` and `wheel` are
  removed from the runtime stage. They are not needed to run gunicorn, and the
  packages setuptools vendors were the source of two HIGH CVEs.
- **Non-root.** The container runs as the `app` user, enforced again by
  `securityContext` in `deployment.yaml`.
- **Safe worker creation.** Background CPU and memory workers use the `spawn`
  multiprocessing context instead of forking the multithreaded web process.
- **Scanned in CI.** `load-harness-ci.yml` runs Trivy against the built image
  with `severity: CRITICAL,HIGH` and `exit-code: 1`, so a vulnerable image
  fails the build rather than shipping.

## Deployment on EKS

Managed via FluxCD GitOps:

- `k8s/applications/load-harness/deployment.yaml`
- `k8s/applications/load-harness/service.yaml`
- `k8s/applications/load-harness/hpa.yaml`
- `k8s/applications/load-harness/servicemonitor.yaml`

## Observability Integration

Currently deployed:

- **metrics-server** — HPA metrics source
- **Prometheus** — Metrics collection (kube-prometheus-stack)
- **Grafana** — Dashboards and visualization
- **ServiceMonitor** — Auto-discovery of application metrics

## Extending or replacing the Harness

The Harness exists to give the platform something real to deploy, scale,
canary and measure. It is meant to be replaced.

Replacing it is a small migration, not an image-only toggle. Preserve or
deliberately update this contract:

1. The Deployment must expose the Service's named HTTP port, provide distinct
   liveness and readiness endpoints, keep resource requests for HPA, and expose
   Prometheus metrics compatible with the `ServiceMonitor`.
2. The image repository, immutable bootstrap tag, release-please package name,
   Flux `ImageRepository`/`ImagePolicy`, and CI `ECR_REPOSITORY` must move
   together. `scripts/validate-template-contract.sh` currently enforces the
   Harness version/tag pair.
3. Flagger's `targetRef`, `autoscalerRef`, Service port, ingress reference,
   webhook routes, and MetricTemplates must match the replacement. The current
   analysis relies specifically on NGINX ingress metrics and public `/health`
   and `/ready` endpoints.
4. Update the Kubernetes Secret contract if the replacement does not use the
   Harness's optional API key and required Flask session key.

Validate the replacement through build, schema and policy checks first. Canary
promotion, rollback, HPA behavior, and teardown still require an approved live
cycle in a configured private copy.

Keeping the Harness alongside your own workload is also reasonable - it is a
useful way to generate load and confirm autoscaling still behaves after a
change.
