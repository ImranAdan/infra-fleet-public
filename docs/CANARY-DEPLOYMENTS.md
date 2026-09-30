# Canary Deployments: Objects and Routes

[Documentation index](README.md)

[Progressive delivery](PROGRESSIVE-DELIVERY.md) explains the flow, the gates
and how to test it. This page covers what Flagger creates. `<app>` is
`APP_NAME` from the [application contract](APPLICATION-CONTRACT.md),
`load-harness` by default.

## What Flagger owns

When the Canary first appears, Flagger takes over the app's Deployment:

| Object | Role |
|---|---|
| `<app>-primary` Deployment and HPA | The stable revision, serving users |
| `<app>` Deployment | Flux's declared revision. Scaled to 0 except while a new revision is analysed |
| `<app>`, `<app>-primary` and `<app>-canary` Services | Stable, primary and canary endpoints |
| Weighted route | An `HTTPRoute` on the fleet Gateway's `https` listener for `APP_HOSTNAME` |

Flagger copies the pod template to the primary and renames its `app` label to
`<app>-primary`. That is why the NetworkPolicy and any `PodMonitor` select both
labels.

## One route in both profiles

Both profiles use Envoy Gateway (`gatewayapi:v1`), the same gate queries
(`envoy_cluster_upstream_rq*`) and the same load-test target, the
`fleet-gateway` Service. Load tests call it over HTTPS with the app's hostname
(`hey -host ${APP_HOSTNAME} https://…`): `hey` sends that name as TLS SNI and
skips certificate verification, so the local CA's certificate works, and
the gates measure the app rather than the HTTP-to-HTTPS redirect. Requests that
bypass the Gateway, or carry another hostname, never appear in the gate metrics.

## Files

| File | Purpose |
|---|---|
| `k8s/applications/platform/canary.yaml` | The Canary, its gates and webhooks, for any app |
| `k8s/applications/observability/metrictemplate.yaml` | Envoy gate queries |
| `k8s/routing/gateway.yaml` | The shared Gateway, HTTPS redirect and certificate |
| `k8s/infrastructure/flagger/helmrelease.yaml` | Flagger |
| `k8s/infrastructure/flagger-loadtester/helmrelease.yaml` | The load tester that drives analysis traffic |

## Troubleshooting

**`no values found for metric`.** Check that load-test requests reach the
Gateway over HTTPS with the app's hostname; plain HTTP only returns redirects.

**Traffic missing from the gates.** Check the route is attached:
`kubectl get gateway fleet -n envoy-gateway-system -o jsonpath='{.status.listeners[*].attachedRoutes}'`
should show one route on each listener.
