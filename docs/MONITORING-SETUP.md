# Monitoring Setup Guide

Guide to the observability stack shared by the local and AWS staging profiles.

## Overview

The platform uses **kube-prometheus-stack** (Helm chart v67.4.0) to provide:

- **Prometheus**: Metrics collection and time-series database
- **Grafana**: Dashboards and visualization
- **kube-state-metrics**: Kubernetes object metrics
- **node-exporter**: Node-level metrics (CPU, memory, disk)
- **PodMonitors and ServiceMonitors**: Auto-discovery of workload metrics

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     observability namespace                  │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌────────────────┐  │
│  │  Prometheus │────│   Grafana   │    │ kube-state-    │  │
│  │   (scrape)  │    │ (visualize) │    │    metrics     │  │
│  └──────┬──────┘    └─────────────┘    └────────────────┘  │
│         │                                                   │
│         │ PodMonitor                                        │
│         ▼                                                   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                   applications namespace                     │
│                                                             │
│  ┌─────────────┐                                            │
│  │ load-harness│──► /metrics (Prometheus format)            │
│  │   :5000     │                                            │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

## Access

### Port forwarding

Use the facade so it selects the active profile's namespace and service:

```bash
./fleet access --profile local --service prometheus
./fleet access --profile local --service grafana
```

Then access:
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

### Grafana Credentials

| Setting | Value |
|---------|-------|
| Username | `admin` |
| Password | Value supplied as the `GRAFANA_ADMIN_PASSWORD` Actions secret |

The rebuild workflow writes this value to the runtime-only
`grafana-admin-credentials` Kubernetes Secret. No default cluster password is
committed.

## Configuration

### Prometheus

| Setting | Value | Notes |
|---------|-------|-------|
| Retention | 2 days | Ephemeral stack, no long-term storage |
| Max Storage | 1GB | Constrained for t3.large |
| Scrape Interval | 15s | Default |
| CPU Request | 100m | |
| Memory Request | 256Mi | |
| CPU Limit | 500m | |
| Memory Limit | 512Mi | |

### Grafana

| Setting | Value | Notes |
|---------|-------|-------|
| Persistence | Disabled | Dashboards lost on restart |
| CPU Request | 50m | |
| Memory Request | 128Mi | |
| CPU Limit | 200m | |
| Memory Limit | 256Mi | |

### Disabled Components

| Component | Reason |
|-----------|--------|
| Alertmanager | Saves 1 pod, not needed for ephemeral stack |
| Admission Webhooks | Known timeout issues |

## Monitor configuration

The load harness exposes Prometheus metrics through a PodMonitor so Flagger's
generated primary and canary pods remain discoverable:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: load-harness
  namespace: applications
spec:
  selector:
    matchExpressions:
      - key: app
        operator: In
        values: [load-harness, load-harness-primary]
  podMetricsEndpoints:
    - port: http
      path: /metrics
      interval: 15s
```

Prometheus discovers both monitor types across all namespaces:
```yaml
serviceMonitorSelectorNilUsesHelmValues: false
serviceMonitorSelector: {}
podMonitorSelectorNilUsesHelmValues: false
podMonitorSelector: {}
```

## Verifying the Setup

### Check Prometheus Targets

```bash
# Port-forward to Prometheus
kubectl port-forward -n observability prometheus-kube-prometheus-stack-prometheus-0 9090:9090

# Open http://localhost:9090/targets
# Verify load-harness appears as "UP"
```

### Check Metrics Collection

```bash
# Query Prometheus for Flask metrics
curl -s "http://localhost:9090/api/v1/query?query=flask_http_request_total" | jq .
```

### Useful PromQL Queries

| Metric | Query |
|--------|-------|
| Request rate | `rate(flask_http_request_total[1m])` |
| Request latency (p95) | `histogram_quantile(0.95, rate(flask_http_request_duration_seconds_bucket[5m]))` |
| Error rate | `rate(flask_http_request_total{status=~"5.."}[5m])` |
| Pod CPU usage | `rate(container_cpu_usage_seconds_total{pod=~"load-harness.*"}[5m])` |
| Pod memory | `container_memory_usage_bytes{pod=~"load-harness.*"}` |

## Importing Dashboards

Since Grafana uses ephemeral storage, dashboards must be imported after each restart.

### Option 1: Import JSON File

1. Open Grafana at http://localhost:3000
2. Go to **Dashboards** → **Import**
3. Upload JSON from `applications/load-harness/monitoring/grafana-dashboard.json`
4. Select **Prometheus** as the datasource
5. Click **Import**

### Option 2: Import via ConfigMap

```bash
# Create ConfigMap with dashboard JSON
kubectl create configmap load-harness-dashboard \
  -n observability \
  --from-file=grafana-dashboard.json=applications/load-harness/monitoring/grafana-dashboard.json

# Label it for Grafana sidecar discovery
kubectl label configmap load-harness-dashboard \
  -n observability \
  grafana_dashboard=1
```

### Option 3: Import Community Dashboard

1. Go to **Dashboards** → **Import**
2. Enter ID: `10924` (Flask Prometheus Exporter)
3. Select **Prometheus** datasource
4. Click **Import**

## Resource Constraints

### t3.large Pod Capacity (35 pods max)

Current allocation:
```
observability:  4 pods
├── prometheus-kube-prometheus-stack-prometheus-0
├── kube-prometheus-stack-grafana-*
├── kube-prometheus-stack-operator-*
└── kube-prometheus-stack-kube-state-metrics-*
```

**Note**: node-exporter runs as DaemonSet (1 per node), not counted in pod limit.

## Troubleshooting

### Prometheus Not Scraping Target

1. Check the application PodMonitor exists:
   ```bash
   kubectl get podmonitor -n applications
   ```

2. Check Prometheus config includes target:
   ```bash
   kubectl port-forward -n observability prometheus-kube-prometheus-stack-prometheus-0 9090:9090
   # Open http://localhost:9090/config
   ```

3. Verify pod labels match the PodMonitor selector:
   ```bash
   kubectl get pods -n applications --show-labels
   ```

### Grafana Dashboard Not Loading

1. Verify Prometheus datasource is configured:
   - Go to **Configuration** → **Data Sources**
   - Should show "Prometheus" with URL `http://prometheus-operated:9090`

2. Check Prometheus is running:
   ```bash
   kubectl get pods -n observability
   ```

### High Memory Usage

If Prometheus OOMs:
1. Reduce retention: `retention: 1d`
2. Reduce storage: `retentionSize: "500MB"`
3. Limit scraped metrics via relabeling

## Related Documentation

- [Load Harness Monitoring Guide](../applications/load-harness/monitoring/README.md)
- [Cost Optimization Guide](./COST-OPTIMIZATION-GUIDE.md)
- [EKS Access Guide](./EKS-ACCESS.md)
