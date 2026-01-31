# Progressive Delivery with Flagger

**Status**: Implemented (2025-12-26)
**Last Updated**: 2026-01-01

This document describes the progressive delivery setup using Flagger for automated canary deployments.

---

## Overview

Flagger is a progressive delivery controller that automates the promotion of canary deployments using metrics from Prometheus. When a new version of load-harness is deployed, Flagger:

1. Creates a canary deployment alongside the primary (stable) deployment
2. Gradually shifts traffic from primary to canary
3. Analyzes Prometheus metrics at each step
4. Automatically rolls back if metrics fail thresholds
5. Promotes the canary to primary if all checks pass

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      CANARY DEPLOYMENT FLOW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐    Image Change    ┌──────────────────┐      │
│   │    GitHub    │ ────────────────── │   Flux Image     │      │
│   │   Actions    │                    │   Automation     │      │
│   └──────────────┘                    └────────┬─────────┘      │
│                                                │                 │
│                                                ▼                 │
│                                       ┌──────────────────┐      │
│                                       │   Deployment     │      │
│                                       │  (load-harness)  │      │
│                                       └────────┬─────────┘      │
│                                                │                 │
│                                                ▼                 │
│   ┌──────────────────────────────────────────────────────┐      │
│   │                     FLAGGER                           │      │
│   │  ┌─────────────┐              ┌─────────────────┐    │      │
│   │  │   PRIMARY   │ ◄── traffic ──│    CANARY      │    │      │
│   │  │   (stable)  │   splitting   │   (new ver)    │    │      │
│   │  └─────────────┘              └────────┬────────┘    │      │
│   │                                        │             │      │
│   │                        ┌───────────────┘             │      │
│   │                        ▼                             │      │
│   │              ┌─────────────────┐                     │      │
│   │              │   PROMETHEUS    │                     │      │
│   │              │   (metrics)     │                     │      │
│   │              └────────┬────────┘                     │      │
│   │                       │                              │      │
│   │         success rate > 99%? ───────────┐             │      │
│   │         latency p99 < 500ms?           │             │      │
│   │                       │                │             │      │
│   │                   YES │            NO  │             │      │
│   │                       ▼                ▼             │      │
│   │              ┌────────────┐    ┌────────────┐        │      │
│   │              │  PROMOTE   │    │  ROLLBACK  │        │      │
│   │              │  to primary│    │  to primary│        │      │
│   │              └────────────┘    └────────────┘        │      │
│   └──────────────────────────────────────────────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Flagger Controller

**Location**: `k8s/infrastructure/flagger/helmrelease.yaml`

The Flagger controller runs in the `flux-system` namespace and watches for Canary resources.

**Configuration**:

| Setting | Value | Description |
|---------|-------|-------------|
| `meshProvider` | `kubernetes` | No service mesh required |
| `metricsServer` | `http://kube-prometheus-stack-prometheus.observability:9090` | Prometheus endpoint |

### 2. Canary Resource

**Location**: `k8s/applications/load-harness/canary.yaml`

The Canary CRD tells Flagger how to manage the load-harness deployment.

**Configuration**:

| Setting | Value | Description |
|---------|-------|-------------|
| `targetRef` | `Deployment/load-harness` | Deployment to manage |
| `autoscalerRef` | `HPA/load-harness` | HPA for coordinated scaling |
| `analysis.interval` | `30s` | Time between metric checks |
| `analysis.stepWeight` | `10` | Traffic increment per step (%) |
| `analysis.maxWeight` | `50` | Maximum canary traffic (%) |
| `analysis.threshold` | `3` | Successful checks before promotion |

### 3. Metrics

Flagger uses **custom MetricTemplates** that query NGINX ingress metrics. This
is required because prometheus-operator relabels the application namespace to
`exported_namespace`, while the ingress controller keeps `namespace` set to
`ingress-nginx`. The templates live in
`k8s/applications/load-harness/metrictemplate.yaml`.

| Metric | Threshold | Template |
|--------|-----------|----------|
| `request-success-rate` | > 99% | `nginx-request-success-rate` |
| `request-duration` | p99 < 500ms | `nginx-request-duration` |

---

## How Traffic Shifting Works

Without a service mesh, Flagger uses **pod scaling** for traffic splitting:

1. **Initial state**: Primary has all replicas, canary has 0
2. **Step 1 (10%)**: Scale canary to ~10% of total pods
3. **Step 2 (20%)**: Scale canary to ~20% of total pods
4. ...continues until maxWeight (50%)...
5. **Promotion**: Canary becomes new primary, old primary scaled down

```
Timeline:
─────────────────────────────────────────────────────────────────────
0:00   │ Primary: 100%  │ Canary: 0%    │ (new image detected)
0:30   │ Primary: 90%   │ Canary: 10%   │ (metrics check: PASS)
1:00   │ Primary: 80%   │ Canary: 20%   │ (metrics check: PASS)
1:30   │ Primary: 70%   │ Canary: 30%   │ (metrics check: PASS)
2:00   │ Primary: 60%   │ Canary: 40%   │ (metrics check: PASS)
2:30   │ Primary: 50%   │ Canary: 50%   │ (metrics check: PASS × 3)
3:00   │ Primary: 0%    │ Canary: 100%  │ (PROMOTED)
─────────────────────────────────────────────────────────────────────
```

---

## Observing Canary Deployments

### Check Canary Status

```bash
# Get all canaries
kubectl get canary -n applications

# Detailed status
kubectl describe canary load-harness -n applications

# Watch in real-time
kubectl get canary load-harness -n applications -w
```

### Status Values

| Status | Description |
|--------|-------------|
| `Initialized` | Canary created, waiting for first deployment |
| `Progressing` | Traffic shifting in progress |
| `Promoting` | Metrics passed, promoting canary to primary |
| `Succeeded` | Canary promoted successfully |
| `Failed` | Metrics failed, rolled back |

### View Flagger Logs

```bash
# Flagger controller logs
kubectl logs -n flux-system deploy/flagger -f

# Filter for load-harness events
kubectl logs -n flux-system deploy/flagger -f | grep load-harness
```

### Example Log Output

```
Initialization done! load-harness.applications
New revision detected! Scaling up load-harness.applications
Starting canary analysis for load-harness.applications
Advance load-harness.applications canary weight 10
Advance load-harness.applications canary weight 20
Advance load-harness.applications canary weight 30
Advance load-harness.applications canary weight 40
Advance load-harness.applications canary weight 50
Promotion completed! Scaling down load-harness.applications
```

---

## Testing Automatic Rollback

Use the `FAIL_RATE` chaos injection feature to test rollback:

### Step 1: Enable Chaos Injection

Edit the deployment to add failures:

```yaml
# k8s/applications/load-harness/deployment.yaml
env:
  - name: FAIL_RATE
    value: "0.3"  # 30% of requests will return 500
```

### Step 2: Push and Watch

```bash
# Commit and push the change
git add k8s/applications/load-harness/deployment.yaml
git commit -m "test: enable chaos injection for rollback testing"
git push

# Watch canary status
kubectl get canary load-harness -n applications -w
```

### Step 3: Expected Behavior

```
Timeline with FAIL_RATE=0.3:
─────────────────────────────────────────────────────────────────────
0:00   │ Primary: 100%  │ Canary: 0%    │ (new image detected)
0:30   │ Primary: 90%   │ Canary: 10%   │ (metrics check...)
       │                │               │ success_rate=70% < 99% ❌
1:00   │ Primary: 100%  │ Canary: 0%    │ (ROLLBACK)
─────────────────────────────────────────────────────────────────────

Flagger logs:
Halt advancement load-harness.applications request-success-rate 70.00 < 99
Rolling back load-harness.applications failed checks threshold reached 1
Canary failed! Scaling down load-harness.applications
```

### Step 4: Cleanup

Revert the FAIL_RATE change:

```yaml
env:
  - name: FAIL_RATE
    value: "0.0"  # Disable chaos
```

---

## Prometheus Metrics

Flagger queries these metrics from NGINX ingress metrics:

### Success Rate

```promql
# Request success rate (non-5xx / total)
sum(
  rate(
    nginx_ingress_controller_requests{
      exported_namespace="applications",
      ingress="load-harness",
      status!~"5.."
    }[1m]
  )
)
/
sum(
  rate(
    nginx_ingress_controller_requests{
      exported_namespace="applications",
      ingress="load-harness"
    }[1m]
  )
) * 100
```

### Request Duration (p99)

```promql
# 99th percentile latency (ms)
histogram_quantile(0.99,
  sum(
    rate(
      nginx_ingress_controller_request_duration_seconds_bucket{
        exported_namespace="applications",
        ingress="load-harness"
      }[1m]
    )
  ) by (le)
) * 1000
```

### View in Prometheus

```bash
# Port-forward to Prometheus
kubectl port-forward -n observability svc/kube-prometheus-stack-prometheus 9090:9090

# Open http://localhost:9090 and run the queries above
```

---

## Troubleshooting

### Canary Stuck in "Initialized"

The deployment hasn't changed since Flagger was installed.

**Solution**: Make any change to the deployment (e.g., add an annotation) to trigger the first canary:

```bash
kubectl annotate deployment load-harness -n applications \
  flagger.app/trigger="$(date +%s)"
```

### Canary Fails Immediately

Check if metrics are available:

```bash
# Verify ServiceMonitor is working
kubectl get servicemonitor -n applications

# Check Prometheus targets
# Port-forward and check Status > Targets
```

Also verify that traffic goes through the NGINX ingress with the correct
`Host` header; direct service calls bypass ingress metrics and result in
"no values found" during analysis (see
`k8s/applications/load-harness/canary.yaml`).

### Canary Never Promotes

Thresholds may be too strict or traffic is too low:

```bash
# Check current metrics
kubectl port-forward -n observability svc/kube-prometheus-stack-prometheus 9090:9090
# Run the PromQL queries above

# Check Flagger analysis results
kubectl describe canary load-harness -n applications
```

### View Flagger Events

```bash
kubectl get events -n applications --field-selector reason=Synced
```

---

## Configuration Reference

### Canary Spec Fields

| Field | Description | Default |
|-------|-------------|---------|
| `targetRef` | Deployment to manage | Required |
| `autoscalerRef` | HPA for coordinated scaling | Optional |
| `service.port` | Service port | Required |
| `analysis.interval` | Time between checks | `1m` |
| `analysis.threshold` | Successful checks before promotion | `1` |
| `analysis.maxWeight` | Max canary traffic % | `50` |
| `analysis.stepWeight` | Traffic increment % | `10` |
| `analysis.metrics` | Metric thresholds | Required |

### MetricTemplate Names

| Name | Description |
|------|-------------|
| `nginx-request-success-rate` | Percentage of non-5xx responses |
| `nginx-request-duration` | Request latency histogram (p99) |

---

## Related Documentation

- [Flagger Official Docs](https://docs.flagger.app/)
- [MONITORING-SETUP.md](MONITORING-SETUP.md) - Prometheus configuration
- [RELEASE-ENGINEERING-ROADMAP.md](RELEASE-ENGINEERING-ROADMAP.md) - Phase 5 overview
- [Load-Harness README](../applications/load-harness/README.md) - FAIL_RATE documentation

---

## Changelog

- **2025-12-26**: Initial implementation with Kubernetes native provider
