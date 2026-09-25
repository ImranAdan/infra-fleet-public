# Fleet verification map

The maintained index of what the local fleet does for an operator and what
proves each behavior. Read this before driving, then use the feature file.

## Baseline preconditions

- `./fleet up --profile local` has succeeded on this checkout.
- `.claude/skills/verify-fleet/doctor.sh` exits 0.
- `export PATH="$(git rev-parse --git-common-dir)/fleet/local/bin:$PATH" KUBECONFIG="$(git rev-parse --git-common-dir)/fleet/local/kubeconfig"`.
- No other agent is deploying to or testing on this cluster.

## Driving conventions

- Start from a doctor-clean state. After a failed drive, run the doctor again
  before the next.
- Change the cluster only through Git: commit, then `./fleet sync`.
- Reach the app through the gateway with `hey -host`, Prometheus through the
  API proxy. Use port-forwards only for humans.
- Wait for conditions (`kubectl wait`, a canary phase), never fixed sleeps.

## Proof and skip reporting

- Pair every action with a read-only second view of its result.
- Compare numbers against a ground truth you created.
- Record the revision (`git rev-parse HEAD`) and the app (`fleet-app` ConfigMap)
  with every artifact.
- Report an unreachable path with the command tried and the unmet precondition.

## Feature entry contract

Each feature file has an H1, one paragraph on the behavior, and four H2s in
order: `Sub-features`, `How to get to it (user POV)`,
`Driving it with kubectl, flux and hey`, `Gotchas`.

## Features

- [App contract and swap](app-contract.md): select an app, prove the platform
  runs it and names none.
- [Progressive delivery](progressive-delivery.md): canary promotion and
  automatic rollback from Git.
- [Observability](observability.md): gateway golden signals match ground truth;
  dashboards are provisioned from Git.
- [Guardrails](guardrails.md): drift repair, admission rejections and network
  isolation.
