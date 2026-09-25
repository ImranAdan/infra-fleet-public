# Guardrails

Git stays the source of truth, unsafe objects are refused at admission, and
only the gateway, observability and Flux reach the app.

## Sub-features

- `drift-repair` Flux restores a hand-edited label.
- `admission` Kyverno rejects an unsafe rollout, a foreign registry and a
  `latest` tag.
- `isolation` a pod in another namespace cannot reach the app.

## How to get to it (user POV)

- Covered by `./fleet test --profile local`; each check can also be driven
  alone.

## Driving it with kubectl, flux and hey

Preconditions:

- Doctor clean.

- **Drift repair.** Run `kubectl label deployment <app> -n applications managed-by=manual --overwrite`,
  then `flux reconcile kustomization applications --timeout=5m`. Then
  `kubectl get deployment <app> -n applications -o jsonpath='{.metadata.labels.managed-by}'`
  prints `flux`.
- **Admission.** For each of `bad-rollout`, `bad-registry`,
  `bad-registry-sidecar` and `bad-latest-sidecar`, run
  `kubectl apply --dry-run=server -f tests/profiles/admission/<fixture>.yaml`.
  Each fails and names `require-rollout-capacity`, `require-local-images` or
  `block-latest-tag`.
- **Isolation.** From a pod in a fresh namespace, run
  `curl -fsS --connect-timeout 3 http://<app>-primary.applications:<APP_PORT><APP_HEALTH_PATH>`.
  It times out (curl exit 28). From `flagger-loadtester` in `flux-system` the
  same URL succeeds.
- **Proof.** Save each command, its output and its exit code.

## Gotchas

- Admission checks are server-side dry runs: nothing is created.
- Delete any namespace you created for the isolation check.
- The admission fixtures use sample image names; they are data, not platform
  references to an app.
