# Ops Scripts

These scripts operate the cluster in the **current kubectl context**. They are
useful after configuring AWS access. For the local profile, prefer `./fleet
access --profile local --service app|dashboard|grafana|prometheus`; the facade
uses its checkout-owned kubeconfig and never changes the default context.

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

This starts Grafana, Prometheus, and the selected application. It tracks only
the processes it starts and leaves unrelated port-forwards alone.

```
  +--------------+-----------------------+-------------------------+
  | Service      | URL                   | Credentials             |
  +--------------+-----------------------+-------------------------+
  | Grafana      | http://localhost:3000 | admin / <password>      |
  | Prometheus   | http://localhost:9090 | -                       |
  | Selected app | http://localhost:8080 | app-specific            |
  +--------------+-----------------------+-------------------------+
```

Press `Ctrl+C` to stop all port-forwards.

## Individual Port-Forwarding Scripts

### Grafana

Access Grafana dashboards on localhost:

```bash
./ops/port-forward.sh grafana
```

- **URL**: http://localhost:3000
- **Username**: `admin`
- **Password**: Get with:
  ```bash
  kubectl get secret -n observability grafana-admin-credentials \
    -o jsonpath="{.data.admin-password}" | base64 -d && echo
  ```

### Prometheus

Access Prometheus metrics and query interface:

```bash
./ops/port-forward.sh prometheus
```

- **URL**: http://localhost:9090
- **Targets**: http://localhost:9090/targets
- **Query**: http://localhost:9090/graph

### Alertmanager (Currently Disabled)

> **Note**: Alertmanager is disabled to save pod capacity on the single staging node.
> See `k8s/infrastructure/observability/kube-prometheus-stack.yaml` to re-enable.

Access Alertmanager for alert management:

```bash
./ops/port-forward.sh alertmanager
```

- **URL**: http://localhost:9093
- **Alerts**: http://localhost:9093/#/alerts

### Selected application

Access the application named by the deployed `fleet-app` contract:

```bash
./ops/port-forward.sh app
```

- **App**: http://localhost:8080
- App-specific UI, health and API paths are documented in that application's
  README under `applications/<name>/`.

## Usage Tips

- Run scripts in separate terminal windows to access multiple services simultaneously
- Press `Ctrl+C` to stop port-forwarding
- If port is already in use, the script will fail - kill the existing process or use a different port

## Troubleshooting

### Port already in use

```bash
# Find process using port 3000 (example)
lsof -nP -iTCP:3000 -sTCP:LISTEN
# Review the process, then stop it normally with: kill PID
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
