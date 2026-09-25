# App contract and swap

The fleet runs whichever application `k8s/fleet-app/fleet-app.yaml` selects and
names none itself. Swapping the app is a contract change, not a migration.

## Sub-features

- `contract-selected` the live `fleet-app` ConfigMap matches the checkout.
- `contract-render` every shipped app renders in both profiles.
- `swap-live` a committed swap replaces the running app within minutes.
- `swap-back` swapping back restores the default app.
- `platform-agnostic` no platform file names an app.

## How to get to it (user POV)

- `scripts/select-app.sh <name>`, commit, `./fleet sync --profile local`.
- `tests/profiles/app-contract.sh` in CI and locally.

## Driving it with kubectl, flux and hey

Preconditions:

- Doctor clean; the working tree is clean.
- You may change the deployed revision: nobody else is using the cluster.

- **Contract renders.** Run `tests/profiles/app-contract.sh`. It prints
  `<app> renders in both profiles.` for every app and exits 0.
- **Selected app.** Run `kubectl get configmap fleet-app -n flux-system -o jsonpath='{.data.APP_NAME}'`.
  It equals `APP_NAME` in `k8s/fleet-app/fleet-app.yaml`.
- **Swap live.** On a scratch branch run `scripts/select-app.sh podinfo`,
  commit, `./fleet sync --profile local`. Within about 70 s
  `kubectl get deploy -n applications` lists `podinfo` and `podinfo-primary`
  only, and `kubectl get pods -n applications` has none in `ImagePullBackOff`.
- **Served by the new app.** Run `kubectl exec -n flux-system deploy/flagger-loadtester -- curl -s -H 'Host: localhost' http://<gateway-service>.envoy-gateway-system/`.
  podinfo answers JSON with `"message": "Running on Infra Fleet (kind)"`.
- **Swap back.** Check out the original branch and `./fleet sync --profile local`.
  `load-harness-primary` returns within about 60 s.
- **Proof.** Save the `kubectl get deploy -n applications` output and the
  gateway response for each direction with the revision deployed.

## Gotchas

- `sync` deploys HEAD; uncommitted selection changes are refused.
- A sync that stopped midway can leave `applications` suspended. The doctor
  flags it; `./fleet sync` or `up` clears it.
- `ImagePullBackOff` right after a swap means manifests and image tag came
  from different revisions. `sync` holds the app layer to prevent this, so
  treat it as a regression.
- The app's own API key and session secret are regenerated per app; get them
  with `./fleet credentials --profile local`.
