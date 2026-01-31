# LoadHarness

A **synthetic workload generator** for Kubernetes platforms with a web-based dashboard. Generate controlled CPU and memory stress to validate autoscaling, observability pipelines, and system resilience.

---

## Features

- **Web Dashboard** - Interactive UI for triggering and monitoring load tests
- **Three Load Types** - CPU (single-pod), Cluster (distributed), Memory
- **Real-time Metrics** - Live CPU, memory, pod count, and request rate
- **Kubernetes-native** - HPA integration, Prometheus metrics, ALB ingress
- **Local & Cluster Modes** - Automatic behavior adaptation based on environment

---

## Authentication

LoadHarness supports optional API key authentication to protect endpoints.

### How It Works

| Auth Method | Use Case |
|-------------|----------|
| **Session (cookie)** | Browser users - login once via `/ui/login` |
| **X-API-Key header** | API clients - pass header on each request |

### Endpoint Protection

| Endpoint | Auth Required |
|----------|---------------|
| `/health`, `/ready` | No (K8s probes) |
| `/apidocs`, `/apispec.json` | No (Swagger docs) |
| `/ui/login` | No (login page) |
| `/ui/*` | **Session required** (redirects to login) |
| `/`, `/load/*`, `/metrics` | **API key required** |

### Enabling Authentication

Set the `API_KEY` environment variable:

```bash
# Local development (.env file)
API_KEY=your-secret-key

# Kubernetes (via Secret)
kubectl create secret generic load-harness-api-key \
  --from-literal=api-key=$(openssl rand -base64 32)
```

If `API_KEY` is not set, authentication is **disabled** (dev mode).

### Retrieving the API Key (Cluster)

```bash
./ops/get-load-harness-api-key.sh
```

### Using the API with Authentication

```bash
# API requests require X-API-Key header
curl -H "X-API-Key: your-key" http://localhost:8080/load/cpu/status

# Browser users login at /ui/login with the same key
```

---

## Quick Start

### Local Development

```bash
cd applications/load-harness/local-dev
docker compose up --build
```

**Access:**
| URL | Description |
|-----|-------------|
| http://localhost:8080/ui | Web Dashboard |
| http://localhost:8080/apidocs | Swagger API Docs |
| http://localhost:8080/metrics | Prometheus Metrics |
| http://localhost:8080/health | Health Check |

### With Observability Stack

```bash
docker compose --profile observability up --build
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

---

## Web Dashboard

The dashboard provides three load testing tabs, a live metrics panel, and job tracking.

### CPU Load Tab (Single Pod)

Stress-test CPU on the current pod/container with background worker processes.

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Cores | 1-16 | 1 | Number of CPU workers to spawn |
| Duration | 10s-15m | 60s | How long to run the load |
| Intensity | 1-10 | 5 | Computational intensity per cycle |

**Behavior:**
- Non-blocking - returns immediately with `job_id`
- Health probes remain responsive during load
- Track progress in Active Jobs panel

**Local vs Cluster:**
| Mode | Behavior |
|------|----------|
| Local | Runs on docker container, metrics show % of available cores |
| Cluster | Runs on single pod, metrics show **avg** (all pods) and **max** (hottest pod) |

---

### Cluster Load Tab (Distributed)

Distribute work across all pods via Kubernetes Service to trigger HPA scaling.

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Concurrency | 5-50 | 10 | Number of parallel requests |
| Iterations | 100K-2M | 500K | CPU work per request |

**Behavior:**
- Sends concurrent requests to `/load/cpu/work` endpoint
- K8s Service distributes requests across pods
- Results show per-pod load distribution
- Can trigger HPA autoscaling

**Local vs Cluster:**
| Mode | Behavior |
|------|----------|
| Local | Warning: All requests hit same container (not meaningful) |
| Cluster | Requests distributed across 1-8 pods, watch Pod Monitor |

**Recommended Safe Max:**
| Setting | Stable | Chaos Mode |
|---------|--------|------------|
| Concurrency | **25** | 50 |
| Iterations | **1M** | 2M |

- **Stable (25/1M):** Triggers HPA scaling, all pods remain healthy, no 503 errors
- **Chaos (50/2M):** Saturates all pods, causes liveness probe failures, pods killed, 503 errors

> ⚠️ **Note:** Max parameters (50 concurrent / 2M iterations) will overwhelm pods to the point where health probes timeout, causing Kubernetes to kill pods and ALB to return 503. Use for chaos/resilience testing only.

---

### Memory Load Tab (Single Pod)

Allocate and hold memory for a specified duration.

| Parameter | Range (Local) | Range (Cluster) | Default |
|-----------|---------------|-----------------|---------|
| Size | 10MB - 2GB | 10MB - **800MB** | 100MB |
| Duration | 5s - 5m | 5s - 5m | 30s |

**Why 800MB max in cluster?**
- Pod memory limit: **1Gi**
- Baseline usage: ~128Mi
- Safe headroom: ~800MB
- Exceeding this triggers OOMKill

**Behavior:**
- Non-blocking - returns immediately with `job_id`
- All memory pages touched to ensure physical allocation (RSS)
- Memory released after duration or on stop

---

## Live Metrics Panel

Real-time system metrics displayed on the right side, auto-refreshes every 5 seconds.

### Metrics Displayed

| Metric | Local Mode | Cluster Mode |
|--------|------------|--------------|
| **CPU Usage** | Single % (process CPU / available cores) | `avg X% \| max Y%` (% of 100m limit) |
| **Memory Usage** | Single % (RSS / system RAM) | `avg X% \| max Y%` (% of 1Gi limit) |
| **Pod Count** | Always 1 | 1-8 with "HPA Scaled" badge |
| **Request Rate** | req/s from Prometheus | req/s aggregated across pods |

### Why Avg and Max?

In cluster mode, single-pod tests (CPU Load, Memory Load) only affect one pod:
- **Avg** gets diluted by idle pods
- **Max** shows the actual impact on the loaded pod

For distributed tests (Cluster Load), both metrics converge as load spreads.

### Data Sources

| Mode | Source |
|------|--------|
| Local | `psutil` library (process-level metrics) |
| Cluster | Prometheus queries (`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`) |

---

## Pod Monitor Panel

Visible only on **Cluster Load** tab. Shows per-pod CPU and memory breakdown.

| Feature | Description |
|---------|-------------|
| Refresh Rate | Every 3 seconds |
| Pods Shown | Up to 8 (HPA max) |
| CPU Colors | Blue (<50%), Yellow (50-80%), Red (>80%) |
| Memory Colors | Same color coding |

**Local Mode:** Disabled with message explaining it requires Kubernetes cAdvisor metrics.

---

## Active Jobs Panel

Client-side job tracking for CPU Load and Memory Load tests.

**Why client-side?** In Kubernetes with HPA, each pod has independent job state. Polling random pods would show inconsistent results.

| State | Display |
|-------|---------|
| Running | Blue card with countdown timer |
| Completed | Green card (removed after 30s) |

---

## API Reference

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Application info |
| `/health` | GET | Liveness/readiness probe |
| `/metrics` | GET | Prometheus metrics |
| `/system/info` | GET | CPU cores, memory info |
| `/apidocs` | GET | Swagger UI |
| `/ui` | GET | Web Dashboard |

### CPU Load Endpoints

| Endpoint | Method | Blocking | Description |
|----------|--------|----------|-------------|
| `/load/cpu` | POST | No | Start async CPU load job |
| `/load/cpu/status` | GET | - | Get all job statuses |
| `/load/cpu/stop` | POST | - | Stop job(s) by ID or all |
| `/load/cpu/work` | POST | **Yes** | Synchronous work for distributed testing |

**POST /load/cpu** - Start CPU Load
```json
{
  "cores": 2,
  "duration_seconds": 60,
  "intensity": 5
}
```

Response:
```json
{
  "status": "started",
  "job_id": "job_1733541234567",
  "cores": 2,
  "duration_seconds": 60,
  "intensity": 5,
  "message": "CPU load started on 2 core(s). Health probes remain responsive."
}
```

**POST /load/cpu/work** - Synchronous Work (for distributed testing)
```json
{
  "iterations": 500000
}
```

Response:
```json
{
  "status": "completed",
  "iterations": 500000,
  "duration_ms": 245.67,
  "pod_name": "load-harness-abc123"
}
```

### Memory Load Endpoints

| Endpoint | Method | Blocking | Description |
|----------|--------|----------|-------------|
| `/load/memory` | POST | No | Start async memory load job |
| `/load/memory/status` | GET | - | Get all job statuses |
| `/load/memory/stop` | POST | - | Stop job(s) by ID or all |
| `/load/memory/sync` | POST | **Yes** | Legacy blocking endpoint |

**POST /load/memory** - Start Memory Load
```json
{
  "size_mb": 256,
  "duration_seconds": 60
}
```

Response:
```json
{
  "status": "started",
  "job_id": "mem_1733541234567",
  "size_mb": 256,
  "duration_seconds": 60,
  "message": "Memory load started: 256MB for 60s. Health probes remain responsive."
}
```

---

## Parameter Limits

| Parameter | Min | Max | Default |
|-----------|-----|-----|---------|
| `cores` | 1 | 16 (or available) | 1 |
| `duration_seconds` (CPU) | 10 | 900 | 60 |
| `intensity` | 1 | 10 | 5 |
| `iterations` | 1,000 | 10,000,000 | 100,000 |
| `size_mb` | 1 | 2,048 (local) / 800 (cluster) | 50 |
| `duration_seconds` (Memory) | 5 | 300 | 30 |

---

## Local vs Cluster Mode

The application automatically detects its environment and adapts behavior.

| Feature | Local (docker-compose) | Cluster (Kubernetes) |
|---------|------------------------|----------------------|
| Environment variable | `ENVIRONMENT=local` | `ENVIRONMENT=staging` |
| Metrics source | psutil (process) | Prometheus (container) |
| CPU/Memory display | Single percentage | avg % \| max % |
| Memory slider max | ~2GB (system limit) | 800MB (pod safety) |
| Pod count | Always 1 | 1-8 (HPA controlled) |
| Cluster Load tab | Warning banner | Distributed to all pods |
| Pod Monitor | Disabled | Per-pod breakdown |

---

## Kubernetes Configuration

### Resource Limits

```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "1Gi"
    cpu: "100m"
```

### HPA Configuration

| Setting | Value |
|---------|-------|
| Min Replicas | 1 |
| Max Replicas | 8 |
| CPU Target | 50% utilization |
| Scale Up | 1 pod every 15s |
| Scale Down | 1 pod every 60s (stabilization: 60s) |

### Health Probes

| Probe | Path | Initial Delay | Period |
|-------|------|---------------|--------|
| Liveness | `/health` | 30s | 10s |
| Readiness | `/health` | 5s | 10s |

### Ingress

- Type: AWS ALB (Application Load Balancer)
- Scheme: internet-facing
- Path: `/` (all traffic routed to load-harness)

---

## Development

### Docker-First Workflow

No local Python required. All development happens in containers.

```bash
# Start development server with hot reload
cd applications/load-harness/local-dev
docker compose up --build

# Run tests
docker compose --profile test run --rm test

# Run specific test
docker compose run --rm test pytest tests/test_app.py -v -k "test_cpu"
```

### Project Structure

```
applications/load-harness/
├── src/load_harness/
│   ├── app.py                    # Flask app factory
│   ├── wsgi.py                   # WSGI entrypoint (Gunicorn)
│   ├── constants.py              # Centralized configuration & limits
│   ├── load_harness_service.py   # API route handlers
│   ├── services/                 # Service layer
│   │   ├── job_manager.py        # Thread-safe job lifecycle management
│   │   ├── prometheus.py         # Prometheus client abstraction
│   │   └── metrics_provider.py   # Local/Kubernetes metrics providers
│   ├── workers/                  # Background worker implementations
│   │   ├── base.py               # BaseWorker ABC, JobConfig, JobStatus
│   │   ├── cpu_worker.py         # CPU load generation
│   │   └── memory_worker.py      # Memory load generation
│   ├── middleware/               # Request middleware
│   │   ├── auth.py               # API key authentication
│   │   ├── chaos.py              # Chaos injection (FAIL_RATE)
│   │   └── security_headers.py   # HTTP security headers (CSP, HSTS, etc.)
│   ├── dashboard/
│   │   └── routes.py             # Dashboard endpoints
│   ├── static/js/                # Frontend JavaScript
│   │   ├── dashboard.js          # Dashboard interactivity
│   │   └── theme.js              # Dark mode toggle
│   └── templates/
│       ├── dashboard.html        # Main dashboard UI
│       └── partials/
│           ├── live_metrics.html # Metrics panel
│           ├── pod_metrics.html  # Pod monitor panel
│           ├── active_jobs.html  # Jobs panel (legacy)
│           └── result.html       # Test result display
├── tests/
│   ├── conftest.py               # Shared pytest fixtures
│   ├── test_app.py               # API endpoint tests
│   ├── test_security_headers.py  # Security header tests
│   └── test_services.py          # Service layer tests
├── local-dev/
│   ├── docker-compose.yml        # Local dev setup
│   └── prometheus.yml            # Local Prometheus config
└── Dockerfile                    # Production image
```

### Building Production Image

```bash
docker build -t load-harness:local .
docker run -p 8080:8080 -e ENVIRONMENT=production load-harness:local
```

---

## Use Cases

1. **HPA Validation** - Trigger CPU load to test horizontal pod autoscaling
2. **Observability Testing** - Verify Prometheus scraping and Grafana dashboards
3. **Resource Tuning** - Find optimal CPU/memory requests and limits
4. **Chaos Engineering** - Controlled stress scenarios for resilience testing
5. **Load Distribution** - Verify Kubernetes Service load balancing

---

## Troubleshooting

### Memory Load OOMKills Pod (Cluster)
- **Cause:** Allocation exceeds 1Gi limit minus baseline
- **Fix:** UI now caps slider at 800MB in cluster mode

### Live Metrics Show "--"
- **Local:** Prometheus not running (start with `--profile observability`)
- **Cluster:** Check ServiceMonitor and Prometheus scraping

### Cluster Load Shows All Requests to Same Pod
- **Local:** Expected - single container
- **Cluster:** Check Service selector matches pod labels

### Active Jobs Not Updating
- Jobs are tracked client-side in browser
- Refresh page to reset job state

---

## Related Documentation

- [Swagger API Docs](/apidocs) - Interactive API explorer
- [Prometheus Metrics](/metrics) - Raw metrics endpoint
- [Health Check](/health) - Kubernetes probe endpoint

---

Maintained as part of the platform engineering toolkit for distributed system reliability testing.
