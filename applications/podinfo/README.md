# podinfo

A small Go web service by the Flux maintainers, used here as a swap-in
application. It proves the platform names no app of its own: select it in
[`k8s/fleet-app/fleet-app.yaml`](../../k8s/fleet-app/fleet-app.yaml) and
[`k8s/applications/kustomization.yaml`](../../k8s/applications/kustomization.yaml),
then `./fleet sync --profile local` and `./fleet test --profile local`.
See the [application contract](../../docs/APPLICATION-CONTRACT.md).

Its fault switch is `PODINFO_RANDOM_ERROR=true`, which fails about a third of
requests; the acceptance test uses it to prove automatic rollback.
