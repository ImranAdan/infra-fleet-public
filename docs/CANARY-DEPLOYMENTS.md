# Canary Deployments with Flagger

This document describes how canary deployments work in this infrastructure using Flagger with NGINX Ingress.

## Architecture Overview

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    Flagger                          │
                    │  (Progressive Delivery Controller in flux-system)   │
                    └─────────────────────┬───────────────────────────────┘
                                          │ monitors
                                          ▼
┌──────────────┐    ┌─────────────────────────────────────────────────────┐
│   Internet   │───▶│              NLB + NGINX Ingress                    │
└──────────────┘    │  (weighted traffic splitting via canary-weight)     │
                    └───────────────────────┬─────────────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                              │
                    ▼                                              ▼
        ┌───────────────────────┐                    ┌───────────────────────┐
        │   load-harness        │                    │  load-harness-canary  │
        │   (Primary)           │                    │  (New Version)        │
        │   Stable version      │                    │  Under test           │
        └───────────────────────┘                    └───────────────────────┘
```

## How Flagger Works

### On First Deploy

When Flagger sees the Canary resource for the first time, it creates:

1. **load-harness-primary** - Deployment for the stable version (receives production traffic)
2. **load-harness-canary** - Deployment for new versions (scaled to 0 initially)
3. **load-harness** (Service) - Routes traffic between primary and canary

The original `load-harness` Deployment is scaled to 0 - Flagger takes full control.

### On New Version Deployment

When a new image or config change is detected:

1. Canary pods created with new version
2. Pre-rollout webhook runs smoke test
3. Traffic split begins (10% canary, 90% primary)
4. Rollout webhook generates load test traffic
5. Prometheus metrics analyzed every 30s
6. If healthy, increase canary traffic by 10%
7. Repeat until maxWeight (50%) reached
8. After 3 successful iterations at max → promote canary to primary

### Timeline (Happy Path)

```
t=0:00  canary 10% ← analyze (smoke test + load test)
t=0:30  canary 20% ← analyze
t=1:00  canary 30% ← analyze
t=1:30  canary 40% ← analyze
t=2:00  canary 50% ← analyze (max weight)
t=2:30  canary 50% ← iteration 1 of 3
t=3:00  canary 50% ← iteration 2 of 3
t=3:30  canary 50% ← iteration 3 of 3 → PROMOTED
```

## Metrics and Thresholds

Flagger evaluates two metrics during canary analysis:

### Success Rate (nginx-request-success-rate)
- **Measures**: Percentage of HTTP requests that don't return 5xx errors
- **Threshold**: Must be >= 99% (allows only 1% error rate)
- **Rollback if**: Error rate exceeds 1%

### Latency (nginx-request-duration)
- **Measures**: 99th percentile response time in milliseconds
- **Threshold**: Must be <= 500ms
- **Rollback if**: Slowest 1% of requests exceed 500ms

## Load Testing During Canary Analysis

### Why Load Testing is Required

Without traffic during canary analysis, Flagger's metrics return NaN or pass by default. Canaries would promote without actual validation.

### Components

1. **flagger-loadtester** - Helm chart deployed in `applications` namespace
   - Based on `hey` (HTTP load generator)
   - Mounted with API key secret for authenticated requests
   - Triggered via webhooks during canary analysis

2. **Webhooks in Canary Resource**:
   - **pre-rollout**: Smoke test `/health` before traffic shift
   - **rollout**: Continuous load test during each analysis interval

### Traffic Flow

```
flagger-loadtester
       │
       │ hey command with X-API-Key header
       ▼
NGINX Ingress Controller (ingress-nginx namespace)
       │
       │ canary-weight annotation determines routing
       ▼
load-harness-canary service
       │
       ▼
Canary pods
```

**IMPORTANT**: Traffic must route through NGINX Ingress Controller for metrics to be captured. Direct service calls bypass NGINX and won't populate `nginx_ingress_controller_requests` metrics.

## Automatic Rollback

### Rollback Triggers

1. Success rate drops below 99% (more than 1% 5xx errors)
2. p99 latency exceeds 500ms
3. Pod health checks fail
4. 3 consecutive failed metric checks

### On Rollback

1. All traffic immediately returns to primary (stable version)
2. Canary pods are scaled to 0
3. Canary status set to "Failed"
4. Users experience minimal impact (only canary % saw issues)

## Testing Rollback

To test the rollback mechanism:

1. Set `FAIL_RATE=0.5` in deployment.yaml (50% of requests will 500)
2. Commit and push → Flux deploys → Flagger starts canary
3. Watch: `kubectl -n applications get canary -w`
4. Load tester generates traffic through NGINX
5. Flagger detects ~50% success rate (below 99% threshold)
6. After 3 failed checks → Flagger rolls back automatically
7. Revert `FAIL_RATE=0.0` to restore normal operation

### Example Rollback Log

```
Advance load-harness.applications canary weight 10
Advance load-harness.applications canary weight 20
Advance load-harness.applications canary weight 30
Halt load-harness.applications advancement nginx-request-success-rate 10.95 < 99
Halt load-harness.applications advancement nginx-request-success-rate 11.62 < 99
Halt load-harness.applications advancement nginx-request-success-rate 11.07 < 99
Rolling back load-harness.applications failed checks threshold reached 3
Canary failed! Scaling down load-harness.applications
```

## Configuration Files

| File | Purpose |
|------|---------|
| `k8s/applications/load-harness/canary.yaml` | Canary resource with analysis config and webhooks |
| `k8s/applications/load-harness/metrictemplate.yaml` | Custom Prometheus queries for metrics |
| `k8s/infrastructure/flagger/helmrelease.yaml` | Flagger controller deployment |
| `k8s/infrastructure/flagger-loadtester/helmrelease.yaml` | Load tester for synthetic traffic |

## Monitoring Commands

```bash
# Watch canary status
kubectl get canary -n applications -w

# Check Flagger logs
kubectl logs -n flux-system deploy/flagger -f | grep load-harness

# Check load tester logs
kubectl logs -n applications deploy/flagger-loadtester -f

# Verify NGINX is receiving traffic
kubectl logs -n ingress-nginx deploy/nginx-ingress-controller-ingress-nginx-controller --tail=20

# Check success rate in Prometheus
# Query: nginx_ingress_controller_requests{exported_namespace="applications", ingress="load-harness"}
```

## Troubleshooting

### Canary promotes without validation
- **Cause**: No traffic during analysis, metrics return NaN
- **Fix**: Ensure load tester is running and traffic routes through NGINX

### "no values found for metric"
- **Cause**: Prometheus doesn't have the expected labels
- **Fix**: Check MetricTemplates use `exported_namespace` (not `namespace`)

### 401 Unauthorized in load test
- **Cause**: API key not mounted or command syntax wrong
- **Fix**: Verify `/etc/loadtester/secrets/api-key` exists in loadtester pod

### Traffic bypassing NGINX metrics
- **Cause**: Load test hitting service directly instead of ingress
- **Fix**: Update webhook to hit `nginx-ingress-controller-ingress-nginx-controller.ingress-nginx`
