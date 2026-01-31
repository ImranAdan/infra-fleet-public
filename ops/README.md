# Ops Scripts

Operational scripts for accessing cluster services via port-forwarding.

## Prerequisites

Ensure your kubeconfig is configured to access the cluster:

```bash
aws eks update-kubeconfig --name staging --region eu-west-2
```

## Quick Start

Run all port-forwards at once:

```bash
./ops/local-forward.sh
```

This starts Grafana, Prometheus, and Load Harness, then displays:

```
  +--------------+-----------------------+-------------------------+
  | Service      | URL                   | Credentials             |
  +--------------+-----------------------+-------------------------+
  | Grafana      | http://localhost:3000 | admin / <password>      |
  | Prometheus   | http://localhost:9090 | -                       |
  | Load Harness | http://localhost:8080 | -                       |
  +--------------+-----------------------+-------------------------+
```

Press `Ctrl+C` to stop all port-forwards.

## Individual Port-Forwarding Scripts

### Grafana

Access Grafana dashboards on localhost:

```bash
./ops/port-forward-grafana.sh
```

- **URL**: http://localhost:3000
- **Username**: `admin`
- **Password**: Get with:
  ```bash
  kubectl get secret -n observability kube-prometheus-stack-grafana \
    -o jsonpath="{.data.admin-password}" | base64 -d && echo
  ```

### Prometheus

Access Prometheus metrics and query interface:

```bash
./ops/port-forward-prometheus.sh
```

- **URL**: http://localhost:9090
- **Targets**: http://localhost:9090/targets
- **Query**: http://localhost:9090/graph

### Alertmanager (Currently Disabled)

> **Note**: Alertmanager is disabled to save pod capacity on t3.medium.
> See `k8s/infrastructure/observability/kube-prometheus-stack.yaml` to re-enable.

Access Alertmanager for alert management:

```bash
./ops/port-forward-alertmanager.sh
```

- **URL**: http://localhost:9093
- **Alerts**: http://localhost:9093/#/alerts

### Load Harness Application

Access the load-harness application:

```bash
./ops/port-forward-load-harness.sh
```

- **Dashboard**: http://localhost:8080/ui (Web Dashboard)
- **API Docs**: http://localhost:8080/apidocs (Swagger UI)
- **App**: http://localhost:8080
- **Health**: http://localhost:8080/health
- **Metrics**: http://localhost:8080/metrics
- **CPU Load**: http://localhost:8080/load/cpu (POST - background job)
- **CPU Work**: http://localhost:8080/load/cpu/work (POST - synchronous)
- **CPU Status**: http://localhost:8080/load/cpu/status (GET)
- **Memory Load**: http://localhost:8080/load/memory (POST - background job)
- **Memory Status**: http://localhost:8080/load/memory/status (GET)

## Usage Tips

- Run scripts in separate terminal windows to access multiple services simultaneously
- Press `Ctrl+C` to stop port-forwarding
- If port is already in use, the script will fail - kill the existing process or use a different port

## Troubleshooting

### Port already in use

```bash
# Find process using port 3000 (example)
lsof -ti:3000 | xargs kill -9
```

### kubectl connection issues

```bash
# Verify cluster access
kubectl get nodes

# Re-authenticate if needed
aws eks update-kubeconfig --name staging --region eu-west-2
```

### Service not found

```bash
# Check service exists
kubectl get svc -n observability
kubectl get svc -n applications
```
