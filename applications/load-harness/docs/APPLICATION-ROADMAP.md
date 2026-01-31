# Application Roadmap — Load Harness

A Python Flask-based synthetic workload service designed to **stress test the EKS cluster**, exercise **HPA**, validate **ALB ingress**, and provide **observable CPU/memory load** for cost/performance analysis.

## Purpose

This application provides a repeatable, deterministic workload to validate:

- ALB → EKS ingress behavior
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
- An ALB ingress is provisioned via AWS Load Balancer Controller.

## High-Level Architecture

```
User → ALB → Ingress → Service → Pods (Flask/Gunicorn)
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

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Application info |
| `/health` | GET | Health check (liveness/readiness) |
| `/metrics` | GET | Prometheus metrics |
| `/load/cpu` | POST | Blocking CPU load |
| `/load/memory` | POST | Memory allocation load |
| `/load/cpu/sustained` | POST | Non-blocking background CPU load |
| `/load/cpu/sustained/status` | GET | Check sustained load job status |
| `/load/cpu/sustained/stop` | POST | Stop sustained load workers |
| `/apidocs` | GET | Interactive Swagger UI |
| `/apispec.json` | GET | OpenAPI specification |

### POST /load/cpu — Blocking CPU Load

```json
{
  "duration_ms": 500,
  "complexity": 5
}
```

- `duration_ms`: 1-10000 (default: 100)
- `complexity`: 1-10 (default: 5)

### POST /load/memory — Memory Load

```json
{
  "size_mb": 100,
  "duration_ms": 2000
}
```

- `size_mb`: 1-2048 (default: 50)
- `duration_ms`: 1-120000 (default: 1000)

### POST /load/cpu/sustained — Non-Blocking CPU Load

```json
{
  "workers": 2,
  "duration_seconds": 60,
  "complexity": 5
}
```

- `workers`: 1-4 (default: 1)
- `duration_seconds`: 1-300 (default: 30)
- `complexity`: 1-10 (default: 5)

Returns immediately with `job_id` for monitoring. Health probes remain responsive.

## Metrics Exposed

Via `prometheus-flask-exporter`:

- `flask_http_request_total` — Request count by endpoint and status
- `flask_http_request_duration_seconds` — Request latency histogram
- `process_cpu_seconds_total` — Process CPU time
- `process_resident_memory_bytes` — Process memory usage

## Dockerfile

Multi-stage build with security best practices:

```dockerfile
# Multi-stage build for production optimization
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim AS runtime

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/app/.local

# Copy application code
COPY src/ ./src/

# Switch to non-root user
USER app

# Add local Python packages to PATH and set PYTHONPATH
ENV PATH=/home/app/.local/bin:$PATH
ENV PYTHONPATH=/app/src

EXPOSE 8080

# Use environment variable for port, defaulting to 8080
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 load_harness.wsgi:app"]
```

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

## Implementation Roadmap

### Phase 1: Core Load Testing ✅ COMPLETE

- ✅ Flask application with factory pattern
- ✅ `/load/cpu` endpoint with configurable duration and complexity
- ✅ `/load/memory` endpoint for memory pressure testing
- ✅ Prometheus metrics via `prometheus-flask-exporter`
- ✅ Health check endpoint
- ✅ Docker-first development workflow
- ✅ Multi-stage Dockerfile with non-root user
- ✅ CI/CD pipeline with GitHub Actions
- ✅ FluxCD GitOps deployment

### Phase 2: Advanced Load Patterns ✅ COMPLETE

- ✅ Non-blocking sustained CPU load (`/load/cpu/sustained`)
- ✅ Multiprocessing workers for background load
- ✅ Job management (start, status, stop)
- ✅ Health probes remain responsive during sustained load

### Phase 3: API Documentation ✅ COMPLETE

- ✅ OpenAPI/Swagger documentation with Flasgger
- ✅ Interactive Swagger UI at `/apidocs`
- ✅ OpenAPI spec at `/apispec.json`
- ✅ Request/response schemas for all endpoints

### Phase 4: Observability Stack ✅ COMPLETE

- ✅ Prometheus deployment (kube-prometheus-stack)
- ✅ Grafana dashboards
- ✅ ServiceMonitor for auto-discovery
- ✅ HPA configuration

### Phase 5: Future Enhancements (Planned)

- 🔄 Network I/O load endpoints
- 🔄 Disk I/O load endpoints
- 🔄 Chaos engineering patterns
- 🔄 Load test automation with scenarios
- 🔄 Cost-per-request analysis dashboard

---

**Status**: Phases 1-4 complete, Phase 5 planned
**Last Updated**: 2025-12-23
