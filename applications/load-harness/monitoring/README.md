# Load Harness Monitoring Guide

This document explains the monitoring setup for the Load Harness application, including all metrics being tracked, how to interpret them, and the story they tell during load testing.

## Table of Contents

1. [Overview](#overview)
2. [The Load Testing Story](#the-load-testing-story)
3. [Dashboards](#dashboards)
4. [Metrics Reference](#metrics-reference)
5. [Data Sources](#data-sources)
6. [Accessing the Dashboards](#accessing-the-dashboards)
7. [Interpreting Results](#interpreting-results)

---

## Overview

The Load Harness monitoring setup consists of three Grafana dashboards that work together to provide visibility into application performance, infrastructure health, and delivery performance:

| Dashboard | Purpose | Best For |
|-----------|---------|----------|
| **Load Testing Overview** | Full-stack view from API to infrastructure | Watching the complete cascade effect during load tests |
| **Load Harness Dashboard** | Detailed application-level metrics | Deep-diving into Flask application internals |
| **DORA Metrics** | Delivery performance and rollbacks | Tracking deployment velocity and stability |

Both dashboards pull data from Prometheus, which scrapes metrics from multiple sources across the Kubernetes cluster.

---

## The Load Testing Story

When you generate load against the API, a cascade of events occurs. Our dashboards are designed to visualize this story in real-time:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           THE LOAD TESTING CASCADE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. REQUEST HITS API                                                        │
│     └── User or load generator sends HTTP request to /load/cpu endpoint     │
│                          ↓                                                  │
│  2. APPLICATION LAYER RESPONDS                                              │
│     ├── Request Rate increases (requests per second)                        │
│     ├── Response Time may increase under load                               │
│     └── Status codes show success (200) or errors (5xx)                     │
│                          ↓                                                  │
│  3. POD RESOURCES SPIKE                                                     │
│     ├── Container CPU usage increases                                       │
│     ├── Memory consumption grows                                            │
│     └── CPU vs Request % rises (this is what HPA watches)                   │
│                          ↓                                                  │
│  4. HPA NOTICES AND ACTS                                                    │
│     ├── When CPU vs Request % exceeds 50%, HPA triggers                     │
│     ├── Desired replicas increases                                          │
│     └── New pods are scheduled and started                                  │
│                          ↓                                                  │
│  5. NODE FEELS THE PRESSURE                                                 │
│     ├── Node CPU utilization increases                                      │
│     ├── Node Memory usage grows                                             │
│     └── More pods running = more node resources consumed                    │
│                          ↓                                                  │
│  6. LOAD DISTRIBUTES                                                        │
│     ├── Traffic spreads across new pods                                     │
│     ├── Per-pod CPU drops as load is shared                                 │
│     └── Response times stabilize                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why This Matters

Understanding this cascade helps you:

- **Identify bottlenecks**: Is the app CPU-bound? Memory-bound? Network-bound?
- **Tune HPA settings**: Is 50% the right threshold? Should you scale earlier or later?
- **Capacity plan**: How many pods do you need for expected traffic?
- **Detect problems**: Are errors increasing under load? Are response times degrading?

---

## Dashboards

### Dashboard 1: Load Testing Overview

**Purpose**: Provides a bird's-eye view of the entire system during load tests. Organized into three layers that mirror the cascade effect.

#### Section 1: Application Layer
*"What's happening at the API level?"*

These panels show how the application is handling incoming traffic:

| Panel | What It Shows | Why It Matters |
|-------|---------------|----------------|
| **Request Rate** | HTTP requests per second | Indicates current traffic volume. Higher = more load. |
| **Avg Response Time** | Average time to respond to requests | Shows if the app is keeping up. Rising times = struggling. |
| **Error Rate** | Percentage of 5xx errors | Non-zero means something is failing. Target: 0%. |
| **Total Requests** | Cumulative request count | Running total since metrics started. |
| **Response Time Percentiles** | p50, p95, p99 latency | p50 = typical user experience. p99 = worst case. |
| **Requests by Status Code** | Breakdown by HTTP status | Shows distribution of 200s, 404s, 500s over time. |

#### Section 2: Scaling (HPA) Layer
*"How is Kubernetes responding?"*

These panels show how the Horizontal Pod Autoscaler is reacting to load:

| Panel | What It Shows | Why It Matters |
|-------|---------------|----------------|
| **Avg CPU vs Request** | CPU used as % of requested CPU | **KEY METRIC**: HPA scales when this exceeds 50%. |
| **Avg Memory vs Request** | Memory used as % of requested memory | Shows memory pressure relative to allocation. |
| **Pod Count** | Current number of running pods | How many instances are handling traffic. |
| **HPA Pending** | Desired - Current replicas | Non-zero means HPA wants to scale but hasn't finished. |
| **HPA Replicas** | Gauge showing current replicas | Visual indicator of scale level (1-2 in our setup). |
| **CPU vs Request % (HPA View)** | Time series with 50% threshold line | Watch this cross the red line to see HPA trigger. |
| **HPA Scaling History** | Current vs Desired replicas over time | Shows when and how scaling events occurred. |

#### Section 3: Infrastructure Layer
*"What's the impact on the node?"*

These panels show the underlying Kubernetes node health:

| Panel | What It Shows | Why It Matters |
|-------|---------------|----------------|
| **Node CPU** | Overall node CPU utilization | Shows total compute pressure on the machine. |
| **Node Memory** | Overall node memory utilization | Shows total memory pressure. High = risk of OOM. |
| **Node Count** | Number of nodes in cluster | Our setup uses 1 node (t3.medium). |
| **App Pods** | Pods in applications namespace | Count of application workloads. |
| **Namespaces** | Total namespaces in cluster | Cluster organization overview. |
| **Node CPU Over Time** | CPU trend graph | Historical view of node compute usage. |
| **Node Memory Over Time** | Memory trend graph | Historical view of node memory usage. |

---

### Dashboard 2: Load Harness Dashboard

**Purpose**: Detailed view of Flask application internals. Use this for deep-diving into application performance.

| Panel | What It Shows | Why It Matters |
|-------|---------------|----------------|
| **Total Requests (All Pods)** | Sum of all requests across pods | Aggregate traffic volume. |
| **Request Rate (All Pods)** | Combined requests/second | Current throughput across all instances. |
| **HTTP Status Codes (All Pods)** | Status codes by method | Detailed breakdown of response types. |
| **Average Response Time (All Pods)** | Mean latency across pods | Overall response speed. |
| **Average CPU Utilization (All Pods)** | Mean CPU across all pods | Aggregate CPU efficiency. |
| **Average Memory Usage (All Pods)** | Mean memory across all pods | Aggregate memory consumption. |
| **Pod CPU Utilization (Per Pod)** | CPU for each individual pod | Compare pod-to-pod performance. |
| **Pod Memory Usage (Per Pod)** | Memory for each individual pod | Identify memory-hungry pods. |

---

### Dashboard 3: DORA Metrics

**Purpose**: Delivery performance signals from workflows, Flux, and Flagger.

**Panels include**:
- Workflow deploys, failure rate, and lead time (24h)
- Flux deploys and latest applied revision
- Flagger rollbacks and current canary phase

**File**: `applications/load-harness/monitoring/dora-metrics.json`

---

## Metrics Reference

### Application Metrics (from Flask app via ServiceMonitor)

These metrics are exposed by the Flask application at `/metrics` endpoint:

| Metric | Type | Description |
|--------|------|-------------|
| `flask_http_request_total` | Counter | Total HTTP requests received, labeled by method, status, path |
| `flask_http_request_duration_seconds` | Histogram | Request duration distribution in seconds |
| `flask_http_request_duration_seconds_bucket` | Histogram | Bucketed request durations for percentile calculation |
| `flask_http_request_duration_seconds_sum` | Counter | Sum of all request durations |
| `flask_http_request_duration_seconds_count` | Counter | Count of requests (for average calculation) |
| `process_cpu_seconds_total` | Counter | Total CPU time consumed by the Python process |
| `process_resident_memory_bytes` | Gauge | Current memory used by the Python process |

### Container Metrics (from cAdvisor via kubelet)

These metrics come from the Kubernetes container runtime:

| Metric | Type | Description |
|--------|------|-------------|
| `container_cpu_usage_seconds_total` | Counter | Cumulative CPU time consumed by the container |
| `container_memory_working_set_bytes` | Gauge | Current working set memory (cannot be evicted) |

### Kubernetes Metrics (from kube-state-metrics)

These metrics describe the state of Kubernetes objects:

| Metric | Type | Description |
|--------|------|-------------|
| `kube_pod_container_resource_requests` | Gauge | CPU/memory requested by containers |
| `kube_deployment_status_replicas` | Gauge | Number of replicas in a deployment |
| `kube_horizontalpodautoscaler_status_current_replicas` | Gauge | Current replica count managed by HPA |
| `kube_horizontalpodautoscaler_status_desired_replicas` | Gauge | Desired replica count (what HPA wants) |
| `kube_pod_info` | Gauge | Information about pods (used for counting) |
| `kube_node_info` | Gauge | Information about nodes |
| `kube_namespace_created` | Gauge | Namespace creation timestamps (used for counting) |

### Node Metrics (from node-exporter)

These metrics come from the Kubernetes node itself:

| Metric | Type | Description |
|--------|------|-------------|
| `node_cpu_seconds_total` | Counter | CPU time by mode (user, system, idle, etc.) |
| `node_memory_MemTotal_bytes` | Gauge | Total physical memory on the node |
| `node_memory_MemAvailable_bytes` | Gauge | Memory available for allocation |

---

## Data Sources

All metrics flow through a collection pipeline:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              METRICS PIPELINE                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐                                                         │
│  │   Flask App     │──── /metrics ────┐                                      │
│  │ (load-harness)  │                  │                                      │
│  └─────────────────┘                  │                                      │
│                                       ▼                                      │
│  ┌─────────────────┐           ┌─────────────┐        ┌─────────────┐        │
│  │  kube-state-    │──────────▶│  Prometheus │───────▶│   Grafana   │        │
│  │    metrics      │           │   (scrapes  │        │ (visualizes │        │
│  └─────────────────┘           │   every 30s)│        │   queries)  │        │
│                                └─────────────┘        └─────────────┘        │
│  ┌─────────────────┐                  ▲                                      │
│  │  node-exporter  │──────────────────┘                                      │
│  │ (node metrics)  │                                                         │
│  └─────────────────┘                                                         │
│                                       ▲                                      │
│  ┌─────────────────┐                  │                                      │
│  │    cAdvisor     │──────────────────┘                                      │
│  │(container stats)│                                                         │
│  └─────────────────┘                                                         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | What It Does | Metrics Provided |
|-----------|--------------|------------------|
| **Flask App** | Exposes application metrics via prometheus_flask_exporter | `flask_http_*`, `process_*` |
| **kube-state-metrics** | Watches Kubernetes API, exposes object states | `kube_*` (deployments, HPAs, pods) |
| **node-exporter** | DaemonSet that exposes node-level metrics | `node_*` (CPU, memory, disk) |
| **cAdvisor** | Built into kubelet, exposes container metrics | `container_*` (CPU, memory per container) |
| **Prometheus** | Scrapes all sources, stores time-series data | Central storage and query engine |
| **Grafana** | Queries Prometheus, renders visualizations | Dashboards you interact with |

---

## Accessing the Dashboards

Since we don't expose Ingress (to avoid ALB costs and finalizer issues), access is via port-forwarding:

### Grafana (Dashboards)

```bash
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

Then open: http://localhost:3000

**Credentials**:
- Username: `admin`
- Password: `prom-operator`

### Prometheus (Direct Queries)

```bash
kubectl port-forward -n observability prometheus-kube-prometheus-stack-prometheus-0 9090:9090
```

Then open: http://localhost:9090

### Importing Dashboards

If dashboards aren't present, import them:

```bash
./ops/import-grafana-dashboard.sh
```

This script imports both dashboards from the JSON files in this directory.

---

## Interpreting Results

### Healthy Load Test Indicators

When running a load test, look for these signs of healthy behavior:

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| Error Rate | 0% | < 1% | > 5% |
| Response Time (p95) | < 500ms | < 1s | > 2s |
| CPU vs Request % | < 80% | 80-100% | > 100% |
| Node CPU | < 70% | 70-90% | > 90% |
| Node Memory | < 70% | 70-90% | > 90% |
| HPA Pending | 0 | 1 (briefly) | Stuck > 0 |

### Common Scenarios

#### Scenario 1: Normal Load Test with HPA Scaling

```
1. Request rate increases to ~50 req/s
2. CPU vs Request % climbs from 20% to 60%
3. Crosses 50% threshold → HPA triggers
4. Pod count increases from 1 to 2
5. Load distributes → CPU vs Request % drops to ~30%
6. Response times remain stable
```

**What you see**: The cascade working as designed.

#### Scenario 2: Overloaded (HPA Can't Keep Up)

```
1. Request rate spikes to 200 req/s
2. CPU vs Request % shoots past 100%
3. HPA scales to max (2 pods)
4. Still overloaded → response times degrade
5. Error rate may increase (timeouts, 503s)
```

**What you see**: Need to increase HPA max replicas or optimize the app.

#### Scenario 3: Memory Pressure

```
1. Memory vs Request % climbing steadily
2. Pod memory approaching limits
3. Eventually: OOMKilled pods
4. Restarts visible in pod count fluctuations
```

**What you see**: Memory leak or insufficent memory limits.

### Key Queries for Troubleshooting

#### Is HPA working?

Look at "HPA Scaling History" panel. You should see:
- **Desired** line spike when CPU threshold is crossed
- **Current** line follow shortly after (30-90 seconds)

#### Why isn't HPA scaling?

Check the "CPU vs Request %" panel:
- If it's below 50%, HPA has no reason to scale
- If it's above 50% but no scaling, check HPA status: `kubectl describe hpa load-harness -n applications`

#### Where's the bottleneck?

1. **High Response Time + Low CPU**: Likely I/O bound or external dependency
2. **High Response Time + High CPU**: CPU bound, need more replicas or optimization
3. **High Error Rate**: Check logs: `kubectl logs -l app=load-harness -n applications`

---

## Quick Reference Card

### Load Test Command

```bash
# Generate CPU-intensive load (synchronous work endpoint)
hey -n 1000 -c 10 -m POST -H "Content-Type: application/json" \
    -d '{"iterations": 1000000}' http://<endpoint>/load/cpu/work

# Quick health check
hey -n 100 -c 5 http://<endpoint>/health
```

### Key Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| CPU vs Request % | 50% | HPA scale-up trigger |
| Node CPU | 90% | Consider larger node or cluster autoscaler |
| Error Rate | 1% | Investigate application logs |
| p99 Latency | 2s | User experience degraded |

### Dashboard URLs (via port-forward)

| Dashboard | URL |
|-----------|-----|
| Load Testing Overview | http://localhost:3000/d/load-testing-overview |
| Load Harness Dashboard | http://localhost:3000/d/af5hm8x33un7kf |
| Prometheus | http://localhost:9090 |

---

## Files in This Directory

| File | Description |
|------|-------------|
| `grafana-dashboard.json` | Load Harness application-focused dashboard |
| `load-testing-overview.json` | Full-stack load testing dashboard |
| `dora-metrics.json` | DORA metrics dashboard for delivery performance |
| `README.md` | This documentation file |

---

## Further Reading

- [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Prometheus Query Language (PromQL)](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [kube-prometheus-stack Helm Chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Flask Prometheus Exporter](https://github.com/rycus86/prometheus_flask_exporter)
