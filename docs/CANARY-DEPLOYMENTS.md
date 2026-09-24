# Canary Deployments: Objects and the AWS Route

[Documentation index](README.md)

> **Deployment preview:** the AWS route depends on retired community
> `ingress-nginx`, which no longer receives security fixes. It documents the
> current lab, not a production rollout design. See [../SECURITY.md](../SECURITY.md).

[Progressive delivery](PROGRESSIVE-DELIVERY.md) explains the flow, the gates
and how to test it. This page covers what Flagger creates, and what differs on
AWS staging. `<app>` is `APP_NAME` from the
[application contract](APPLICATION-CONTRACT.md), `load-harness` by default.

## What Flagger owns

When the Canary first appears, Flagger takes over the app's Deployment:

| Object | Role |
|---|---|
| `<app>-primary` Deployment and HPA | The stable revision, serving users |
| `<app>` Deployment | Flux's declared revision. Scaled to 0 except while a new revision is analysed |
| `<app>`, `<app>-primary` and `<app>-canary` Services | Stable, primary and canary endpoints |
| Weighted route | An `HTTPRoute` for Envoy Gateway locally; a canary `Ingress` for ingress-nginx on AWS |

Flagger copies the pod template to the primary and renames its `app` label to
`<app>-primary`. That is why the NetworkPolicy and any `PodMonitor` select both
labels.

## AWS staging

| | Local | AWS staging |
|---|---|---|
| Router | Envoy Gateway (`gatewayapi:v1`) | ingress-nginx (`nginx`), via the `<app>` Ingress |
| Gate metrics | `envoy_cluster_upstream_rq*` | `nginx_ingress_controller_requests` and `_request_duration_seconds` |
| Namespace label | not needed (route name) | `exported_namespace`, because prometheus-operator relabels it |
| Load test target | Envoy Gateway service | `nginx-ingress-controller-ingress-nginx-controller.ingress-nginx` |

On AWS, the load test must traverse the ingress with the app's public hostname
(`hey -host ${APP_HOSTNAME}`); requests that bypass it, or carry another Host,
never appear in the metrics the gates read.

## Files

| File | Purpose |
|---|---|
| `k8s/applications/platform/canary.yaml` | The Canary, its gates and webhooks, for any app |
| `k8s/profiles/local/applications/metrictemplate.yaml` | Envoy gate queries |
| `k8s/profiles/aws-staging/applications/metrictemplate.yaml` | ingress-nginx gate queries |
| `k8s/profiles/aws-staging/applications/ingress-nginx.yaml` | The app's Ingress on AWS |
| `k8s/infrastructure/flagger/helmrelease.yaml` | Flagger |
| `k8s/infrastructure/flagger-loadtester/helmrelease.yaml` | The load tester that drives analysis traffic |

## AWS troubleshooting

**`no values found for metric`.** Check that the templates filter on
`exported_namespace`, and that load-test requests reach the Ingress with the
public hostname.

**Traffic missing from the gates.** Watch the controller while a canary runs:
`kubectl logs -n ingress-nginx deploy/nginx-ingress-controller-ingress-nginx-controller --tail=20`.
