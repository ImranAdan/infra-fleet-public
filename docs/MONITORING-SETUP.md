# Monitoring Setup Guide

Comprehensive guide for the observability stack deployed on the EKS cluster.

## Overview

The platform uses **kube-prometheus-stack** (Helm chart v67.4.0) to provide:

- **Prometheus**: Metrics collection and time-series database
- **Grafana**: Dashboards and visualization
- **kube-state-metrics**: Kubernetes object metrics
- **node-exporter**: Node-level metrics (CPU, memory, disk)
- **ServiceMonitors**: Auto-discovery of application metrics

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
│         │ ServiceMonitor                                    │
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

### Port Forwarding (Recommended)

Since no Ingress is configured (to avoid ALB costs and finalizer issues), use port-forwarding:

```bash
# Prometheus UI
kubectl port-forward -n observability prometheus-kube-prometheus-stack-prometheus-0 9090:9090

# Grafana UI
kubectl port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80
```

Then access:
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000

### Grafana Credentials

| Setting | Value |
|---------|-------|
| Username | `admin` |
| Password | `prom-operator` |

**Note**: Change the password in production environments.

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

## ServiceMonitor Configuration

Applications expose Prometheus metrics via ServiceMonitor CRDs. Example for load-harness:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: load-harness
  namespace: applications
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: load-harness
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
```

Prometheus auto-discovers ServiceMonitors across all namespaces due to:
```yaml
serviceMonitorSelectorNilUsesHelmValues: false
serviceMonitorSelector: {}
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

1. Check ServiceMonitor exists:
   ```bash
   kubectl get servicemonitor -n applications
   ```

2. Check Prometheus config includes target:
   ```bash
   kubectl port-forward -n observability prometheus-kube-prometheus-stack-prometheus-0 9090:9090
   # Open http://localhost:9090/config
   ```

3. Verify service labels match ServiceMonitor selector:
   ```bash
   kubectl get svc -n applications --show-labels
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
