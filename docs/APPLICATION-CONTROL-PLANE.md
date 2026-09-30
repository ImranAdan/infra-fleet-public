# Local application control plane

[Documentation index](README.md) · [Application contract](APPLICATION-CONTRACT.md)

The local profile can run any included application without changing the
selected app or committing another revision. Start the fleet, then keep this
command open:

```bash
./fleet access --profile local --service dashboard
```

Open <http://localhost:9000/>. **Launch** deploys an app's complete stack;
**Stop** removes a stack launched from the dashboard. The selected app is the
fleet default and cannot be stopped here. Each running app opens at
`http://<app-name>.localhost:9000/`.

## Reconciliation model

The dashboard reads `fleet-catalog`, a ConfigMap built from every
`k8s/applications/<name>/fleet-app.yaml` at the deployed revision. A launch
creates two Flux Kustomizations in `flux-system`:

1. `app-<name>` applies the app's own Deployment, Service and optional
   monitoring resources from `k8s/applications/<name>`.
2. `app-<name>-platform` fills the shared canary, HPA and NetworkPolicy from
   that app's contract and waits for the first layer.

Both read the same `fleet-local` Git snapshot as the selected app. A stop
deletes the platform layer first and the app layer second. Flux finalizers
prune their inventories before the launch objects disappear.

`./fleet sync --profile local` builds every contracted image and prepares every
declared app secret so a later launch does not compile source or invent runtime
configuration.

## Security boundary

The web process can list live application state and create or delete Flux
launch objects. It cannot edit workloads directly.

- A Kubernetes `ValidatingAdmissionPolicy` accepts only the two labelled launch
  object shapes. It fixes their names, source, paths, deployer identity,
  lifecycle settings, application substitutions, image transform, dependency
  and HPA patch. Remote kubeconfigs, target namespaces and other Flux
  transformations are rejected.
- `app-deployer` can reconcile the application workload types in
  `applications` and ConfigMaps in `observability` for app-owned Grafana
  dashboards. It has no cluster-wide role and cannot change Flux, policy,
  infrastructure, Secrets or namespaces.
- A deny-ingress NetworkPolicy prevents other pods from reaching the control
  API. The supported entry point is a loopback-bound `kubectl port-forward`.
- Dashboard and API requests require the documented `localhost` Host header,
  which prevents a hostile DNS name rebound to the loopback port-forward from
  becoming same-origin. Launch and Stop also require `X-Fleet-Action: 1`;
  ordinary cross-origin requests cannot send it without a CORS preflight,
  which the server does not grant.
- The `applications` namespace has a permanent default-deny ingress policy.
  Each app's platform layer adds its explicit Gateway, load-test, monitoring
  and same-app paths, so a partial launch or asynchronous stop cannot expose a
  workload while its app-specific policy is absent.
- App traffic is proxied through Envoy Gateway to the app's route host,
  `<app-name>.apps.localhost`, over TLS verified against the local CA. The dashboard does not bypass the declared ingress path or disable
  certificate verification.

The dashboard is a local operator tool. It is not installed by the AWS profile
and has no user accounts or public exposure model.

## States and recovery

**Not running** means neither an app Deployment nor Canary is present.
**Starting** means launch objects exist but the primary is not ready.
**Running** means a primary replica is ready; the card also shows the Canary
phase, including a previous rollback.

A repeated Launch is idempotent. If a previous Stop is still finalising, the
API returns a conflict and asks the operator to retry. If only one of the two
launch objects was created, Stop removes the partial stack. `./fleet test
--profile local` exercises the admission boundary, launch, Gateway access,
removal, API isolation and the selected app's normal delivery tests.

For diagnosis:

```bash
./fleet status --profile local
kubectl --kubeconfig "$(git rev-parse --git-common-dir)/fleet/local/kubeconfig" \
  --context kind-infra-fleet-local get kustomizations -n flux-system
```

Run `./fleet sync --profile local` after committing changes; it reconciles the
control plane and every currently launched app to the new revision. Sync holds
all app reconcilers until the Git snapshot and image tag agree. If a launched
app becomes the selected app, sync prunes its launch objects first and transfers
ownership to the fleet's selected-application layer. The selected app and each
launched app are then promoted one at a time. Sync exits successfully only when
every requested revision has reached its generated primary; a Flagger rollback
leaves the previous primary serving and makes sync fail.
