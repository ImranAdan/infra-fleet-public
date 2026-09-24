# Application contract

[Documentation index](README.md)

The fleet is a platform; the application is a plug-in. The platform names no
application of its own: it reads the one it runs from
[`k8s/fleet-app/fleet-app.yaml`](../k8s/fleet-app/fleet-app.yaml). Load Harness
is the default. [podinfo](../applications/podinfo/README.md) ships alongside it
to prove the swap works.

## Swap the application

```bash
scripts/select-app.sh podinfo      # or load-harness
git commit -am "chore: run podinfo"
./fleet sync --profile local
./fleet test --profile local
```

`select-app.sh` copies the app's contract into `k8s/fleet-app/fleet-app.yaml`
and points [`k8s/applications/kustomization.yaml`](../k8s/applications/kustomization.yaml)
at the app's manifests. Nothing else changes.

## What an application brings

| Where | What |
|---|---|
| `applications/<name>/` | Source with a `Dockerfile`. A `FROM` line pinning an upstream image by digest is enough. |
| `k8s/applications/<name>/fleet-app.yaml` | Its contract values (below). |
| `k8s/applications/<name>/` | A `Deployment` and a `Service`, plus anything app-specific such as a `PodMonitor` or dashboards. |

The Deployment must:

- be named `<name>`, label its pods `app: <name>` and name its main container `<name>`;
- use the image `app`; the platform binds it to the image it built or released;
- listen on `APP_PORT`, with readiness and liveness probes and CPU and memory
  requests and limits;
- use `RollingUpdate` with `maxUnavailable: 0` and `maxSurge` above zero;
- run as a non-root numeric user with a read-only root filesystem and no
  privilege escalation.

The contract values:

| Key | Meaning | Load Harness | podinfo |
|---|---|---|---|
| `APP_NAME` | Deployment, container, pod label and image name | `load-harness` | `podinfo` |
| `APP_SOURCE` | Build context | `applications/load-harness` | `applications/podinfo` |
| `APP_PORT` | Container and canary port | `5000` | `9898` |
| `APP_HEALTH_PATH` | Smoke-tested before each canary | `/health` | `/healthz` |
| `APP_LOAD_PATH` | Requested through the gateway during analysis | `/apispec.json` | `/` |
| `APP_SECRETS` | `secret:key` pairs the platform generates | API and session keys | none |
| `APP_FAULT_ENV` | `NAME=value` that makes the app fail requests | `FAIL_RATE=1.0` | `PODINFO_RANDOM_ERROR=true` |

## What the platform provides

- **Progressive delivery.** A Flagger canary analysed at the gateway (Envoy
  locally, ingress-nginx on AWS), so the app needs no metrics of its own.
- **Autoscaling and isolation.** An HPA on CPU and a NetworkPolicy that admits
  only the gateway, observability and Flux.
- **Monitoring.** Container CPU, memory and restarts from cAdvisor and
  kube-state-metrics, and request rate, errors and latency from the gateway.
- **Admission.** Kyverno enforces images from the profile's registry, no
  `latest` tags and rollout capacity.
- **Variables.** Flux substitutes `${APP_*}`, `${ENVIRONMENT}` (`kind` or
  `staging`), `${PUBLIC_SCHEME}` (`http` or `https`), `${APP_HOSTNAME}` and
  `${RUNTIME_CONFIG_REVISION}` into the app's manifests. Kustomize drops the
  quotes around a variable, so a value that reads as a number or boolean
  becomes one; give variables values that stay strings.

## AWS staging

The local profile builds the image from `APP_SOURCE`. AWS runs released images
from ECR, so an app also needs:

1. an ECR repository named `APP_NAME` (`infrastructure/permanent/ecr.tf`);
2. a CI workflow that publishes `vX.Y.Z` tags there, called by
   `rebuild-stack.yml` in place of `load-harness-ci.yml`;
3. its first release tag on the `app` image in
   `k8s/profiles/aws-staging/applications/kustomization.yaml`;
4. its `APP_SECRETS` created by `rebuild-stack.yml`.

Flux image automation then follows the app's releases.

## How the swap stays proven

[`tests/profiles/app-contract.sh`](../tests/profiles/app-contract.sh) runs in
CI. It fails if `k8s/fleet-app` drifts from the selected app's contract, if any
platform file names an app, or if any app cannot be selected: each is swapped
in on a scratch worktree and both profiles must render completely.
`./fleet test --profile local` then proves drift repair, admission, monitoring,
isolation, promotion and rollback for whichever app is selected.
