# Application control plane

The local dashboard launches and stops any non-selected app through confined
Flux Kustomizations, while other pods cannot call its control API.

## Sub-features

- `catalog` every shipped contract appears with live state.
- `launch` a second app reconciles from the deployed revision and answers
  through Envoy Gateway.
- `stop` Flux prunes the launched stack.
- `handoff` selecting a launched app removes its launch objects before the
  fleet root takes ownership.
- `confinement` admission fixes the source, paths, deployer identity,
  substitutions, image transform, dependency and HPA patch.
- `isolation` pods outside `fleet-control` cannot reach the dashboard Service.

## How to get to it (user POV)

- Run `./fleet access --profile local --service dashboard`, then open
  `http://localhost:9000/`.
- `./fleet test --profile local` drives one complete launch and stop.

## Driving it with kubectl, flux and hey

Preconditions:

- Doctor clean; the working tree revision is deployed.
- At least one non-selected contract is present.

- **Launch.** POST `/api/apps/<name>/launch` from inside the control-plane pod
  with `X-Fleet-Action: 1`. Both `app-<name>` Kustomizations become Ready.
- **Route.** Request `APP_HEALTH_PATH` from that pod through
  `<name>.localhost:9000`; the dashboard verifies TLS and the app returns 2xx.
- **Stop.** POST `/api/apps/<name>/stop`; both Kustomizations disappear and the
  app Canary is pruned.
- **Isolation.** A curl from `flagger-loadtester` to
  `http://control-plane.fleet-control/api/apps` times out. The Kubernetes API
  service proxy still returns `ok` from `/healthz`, proving the pod itself is
  healthy.
- **Confinement.** A server-side dry-run as the dashboard service account with
  an arbitrary image is denied by `control-plane-launches`; the normal launch
  immediately afterwards succeeds.
- **Proof.** Save the launch objects, route response, deletion and failed
  cross-namespace request.

## Gotchas

- The selected app belongs to the fleet root and cannot be stopped here.
- A Canary phase of `Failed` records the last rollback; a ready primary still
  serves and the dashboard reports it running with that phase visible.
- Port-forwards reconnect after a dashboard pod replacement. Stop them with
  Ctrl-C.
