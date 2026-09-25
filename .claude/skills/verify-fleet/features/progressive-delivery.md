# Progressive delivery

Every new revision reaches traffic through a Flagger canary gated at the
gateway: success rate at least 99% and p99 under 500 ms. A healthy revision is
promoted; one that fails the gates rolls back while the primary keeps serving.

## Sub-features

- `promote` a healthy Git-delivered revision reaches `Succeeded`.
- `rollback` a revision with the app's fault switch reaches `Failed` and the
  primary keeps the previous spec.
- `warm-up` the first gate check finds traffic, so no `no values found` event.
- `load-reaches-app` analysis load returns app responses, not gateway 404s.

## How to get to it (user POV)

- `./fleet test --profile local` exercises promotion and rollback end to end.
- Any committed change to the app Deployment followed by `./fleet sync`.

## Driving it with kubectl, flux and hey

Preconditions:

- Doctor clean and the canary `Initialized` or `Succeeded`.
- You may change the deployed revision.

- **Full cycle.** Run `./fleet test --profile local`. It ends with
  `Local acceptance passed: drift, admission, monitoring, network isolation, promotion and rollback.`
  and exits 0, and restores the deployed revision.
- **Watch a release.** Run `kubectl get canary -n applications -w`. The phase
  goes `Progressing` then `Succeeded` or `Failed`.
- **Read the gates.** Run `kubectl describe canary <app> -n applications`.
  Promotion shows `Advance … canary weight 10` up to `50` and
  `Promotion completed!`; rollback shows `Halt … < 99` (or `> 500`) then
  `Rolling back … failed checks threshold reached 3`.
- **Load reaches the app.** Run `kubectl exec -n flux-system deploy/flagger-loadtester -- hey -n 20 -host localhost http://<gateway-service>.envoy-gateway-system<APP_LOAD_PATH>`.
  The status distribution is the app's (for example `[200] 20`), not `[404]`.
- **Proof.** Save the `describe canary` events and the `./fleet test` output.

## Gotchas

- `no values found for custom metric` means no requests reached the route in
  the last minute. Check the load test first: `-H 'Host: …'` is silently
  ignored by hey.
- Gates are route-wide: Envoy Gateway keeps primary and canary in one cluster
  per rule, so a failing canary shows as a small drop at 10% weight.
- Do not judge a latency failure until the doctor shows node CPU below 70%.
- A canary mid-analysis turns your traffic into gate input. Wait for it to
  finish.
