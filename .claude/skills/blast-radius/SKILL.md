---
name: blast-radius
description: Find what a fleet change could break beyond its diff, and prove the one fact it is safe because of by running real code. Use for "what could this break", before merging a platform, profile, script or app-contract change, or when reviewing a small diff you do not trust.
---

# Blast radius

Listing callers is not the job; `git grep` does that in a second. The job is
the breakage grep cannot show you. Adapted from `blast-radius` in
[pstack](https://github.com/cursor/plugins/tree/main/pstack) (MIT).

## How sure are you

For each fact the change's safety depends on, push it as far down this ladder
as is cheap, and say where it stopped:

1. You said so. Worthless on its own.
2. You pointed at the line: a real `file:line`, or the upstream source.
3. You walked the failure case step by step and it does not reach.
4. You ran it: a script or test calls the real code and fails loudly if you
   are wrong.
5. You reproduced it on the running cluster (`verify-fleet`).

## Where grep stops in this repository

Each of these has broken something here before:

- **Flux substitution.** `${VAR}` is replaced in the rendered text before
  parsing, and kustomize drops the quotes around a variable, so `"${X}"` can
  become a boolean or number. `$${X}` is an escape. Check the rendered value's
  type with `./fleet render --profile <p>`, not the source YAML.
- **Rendered, not raw.** Overlays patch by kind and name. A resource renamed or
  moved in a base silently escapes a patch. Render both profiles
  (`scripts/render-k8s-for-validation.sh <dir>`) and diff the result.
- **Other readers of the same YAML.** Infra Fleet Advisor renders these
  manifests with its own subset of kustomize and Flux, and fails closed on
  anything it does not know, which fails the intent gate. Run its gate locally:
  `../infra-fleet-advisor-public/scripts/intent-gate.sh . <base-sha> <head-sha> <out-dir>`.
  The advisor drills also match literal text in fleet files.
- **The app contract.** `k8s/fleet-app` feeds Flux substitution, the local
  build, secrets, the acceptance test, the CI matrix and the advisor's M-004
  check. A key rename breaks all of them.
- **Order at runtime.** Flux Kustomizations reconcile concurrently unless
  `dependsOn` orders them; a ConfigMap watched with
  `reconcile.fluxcd.io/watch` triggers an immediate re-apply of the old
  revision. `./fleet sync` holds the app layer for this reason.
- **Tools that ignore what you think they read.** `hey -H 'Host: …'` is
  ignored; Grafana's sidecar needs the `grafana_dashboard: "1"` label; an
  image-wide `ENV` also reaches docker-compose command overrides.
- **Pinned consumers.** The intent gate is pinned to an advisor commit, so a
  change the advisor needs to understand must merge there and the pin must be
  bumped first.

## Steps

1. Read the change: the diff, and what it now does differently that the diff
   does not spell out.
2. Find the one fact it is safe because of.
3. Look where grep stops, using the list above.
4. Judge each risk: how likely, how bad. Keep the confirmed ones; list the
   cleared ones separately.
5. Prove the one fact: render, run the gate, or drive it with `verify-fleet`.
   Paste what happened.

## What to hand back

- **What it does**, including the part that is not obvious.
- **The one fact it is safe because of**, the ladder step reached, and the
  proof. Say `unproven` if you could not prove it.
- **Risks**, each with `file:line`, likelihood, cost and how to check.
- **Cleared**: what you checked and why it is fine.
- **Before you merge**: the cheapest check that catches the real bug.
