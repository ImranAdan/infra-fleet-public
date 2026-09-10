# Design Decision Record (DDR)
## Credentials-Free Public Template

**Date:** 2026-09-10
**Author:** Imran Adan
**Status:** Proposed
**Decision Type:** Architecture / Security / CI-CD Execution Model

---

## Summary

`infra-fleet-public` will hold **no cloud credentials and no deployment
secrets**. Its CI proves the code is correct; it does not provision anything.

Provisioning happens in a private repository that supplies its own secrets.
Anyone adopting this template does the same: copy it, make it private, inject
their own values.

---

## Context

This repository is a public template derived from a private working
repository. The two have drifted, and an audit on 2026-09-10 found the public
copy in a state that only an unexercised repository reaches:

| Finding | Detail |
|---------|--------|
| No Actions secrets | `actions/secrets` returned `total_count: 0` |
| Nine workflows depend on `AWS_GITHUB_ACTIONS_ROLE_ARN` | All fail at `Could not load credentials from any providers` |
| `Release Please` had never succeeded | Five runs since the initial commit, five failures |
| Container scanning was inert | `trivy-action@0.33.1` stopped resolving upstream; the job died before scanning |
| A committed CVE fix had never worked | The runtime stage was never patched, and the broken scanner concealed it |

The immediate cause of each was different. The common cause was that **nothing
runs this repository**, so nothing revealed the rot.

Two options were considered for restoring it.

### Option A - harden the public repository and give it credentials

Add the secrets, add `infra-fleet-public` to the AWS role's OIDC trust policy,
and control the resulting exposure.

Reviewing what that exposure would be:

- The role's trust condition is `repo:OWNER/REPO:*`. The wildcard matches every
  ref context including `pull_request`.
- `infra-plan.yml` triggers on `pull_request` and declares `id-token: write`.
- Fork pull requests cannot reach this today, because GitHub withholds secrets
  from them and caps `GITHUB_TOKEN` to read-only.

That last line is the problem with Option A. The control preventing a stranger
from assuming an AWS role would be a GitHub platform default, not a control
this repository owns. Making it safe means a second role, environment-gated
secrets, a scoped trust subject, and a standing obligation to keep
`pull_request_target` out of the repository forever.

### Option B - the public repository holds no credentials

Every check that matters for a template needs no cloud access:

```
terraform fmt / validate / tflint      trivy config
kubeconform / Kyverno                  gitlint / actionlint
unit tests                             container build + image scan
```

Every failure found in the audit was in this set. None of them required AWS.

---

## Decision

**Option B.** `infra-fleet-public` is credentials-free.

- No AWS credentials, no `TF_API_TOKEN`, no cloud provider tokens.
- `infra-fleet-public` is not named in any OIDC trust policy. Adopters name
  **their own** repository in **their own** policy - see "What an adopter does".
- CI validates code, manifests, containers and workflows only.
- `plan`, `apply` and destroy do not run here, and are not expected to.

HCP Terraform remains a hard requirement of this project. It is a declared
prerequisite, not something to abstract behind a backend selector. Adopters
wanting a different state backend can extend the template themselves.

---

## Rationale

**The safest system is the one with nothing worth attacking.** Option A answers
"can this be abused?" with a list of mitigations that must all hold, and keep
holding, across every future change. Option B answers it with "there is no
credential to steal." That property does not decay when someone adds a
workflow.

**It is less work, not more.** Option A requires a plan role, an apply role, a
scoped trust subject, GitHub Environments with reviewers, and permanent
vigilance about triggers. Option B requires deleting configuration.

**A template that cannot deploy is a better template.** An adopter forking this
cannot accidentally point it at someone else's account, because there is no
account named anywhere in it.

**It fixes the drift that caused the audit findings.** Once the private
repository consumes this template rather than duplicating it, the template is
exercised continuously by the thing that depends on it.

---

## Consequences

Accepted, deliberately:

- **`plan` and `apply` do not run in this repository.** Terraform correctness is
  proven by `validate` and static analysis, not by a plan against real state.
- **Provisioning failures are not caught here.** A change that passes CI can
  still fail on `apply` in a consuming repository. That is the cost of not
  holding credentials, and it is the right trade.
- **DORA metrics, cluster verification and nightly destroy do not run here.**
  They are deployment concerns, not template concerns.
- **The private repository becomes the only place infrastructure is applied.**

Gained:

- No secret in this repository can leak, because there is none.
- Public workflow logs cannot expose account identifiers.
- `pull_request` workflows carry no privilege worth escalating to.
- Adopters inherit a template that grants no trust by default.

---

## What an adopter does

1. Copy or fork this repository and **make it private**.
2. Run the permanent stack once, locally, with their own admin credentials.
   This creates the OIDC provider and the CI role in their account.
3. Add their own secrets to their own repository.
4. Set the trust policy to name their repository.

Step 2 is deliberately manual and local. The template cannot bootstrap itself
into any account, which is the property that makes it safe to publish.

---

## Open decision - how credential-dependent workflows behave here

The workflows that need credentials must not silently appear to work. Two ways
to achieve that:

**Fail.** Every run goes red. Honest, but a template whose CI is permanently
red teaches its adopters that red is normal, and hides real failures among
expected ones.

**Skip with an explanation.** When the configuration is absent entirely, the job
skips and writes to the run summary that this is expected in the template, with
a pointer to the setup documentation. When the configuration is *partially*
present, it fails loudly - that is a genuine misconfiguration, not a template
running as designed.

**Recommendation: skip when absent, fail when partial.** It preserves the safety
property - nothing provisions without explicit credentials - while keeping a red
check meaningful. The preflight job added in #13 already implements the
"fail when partial" half.

This needs a decision before implementation.

---

## Implementation sequence

Ordered so that broad trust and live credentials never coexist:

1. **Remove `repo:...:*` from the OIDC trust subject.** Worth doing regardless
   of everything else, and safe to do now while this repository holds no
   secrets.
2. **Decide the skip-versus-fail behaviour above.**
3. **Parameterise identifying values.** `cloud {}` driven by
   `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE`; organisation, repository,
   domain and admin principals as variables with no defaults.
4. **Add `config.example.env`, a bootstrap script and a config doctor**, so
   adoption is one file and one command rather than a checklist.
5. **Document the local bootstrap** as the first step of adoption.

---

## Not decided here

- How the private repository consumes this template - fork and merge, subtree,
  reusable workflows, or a published module. That is a separate decision.
- Whether the removed workflows are deleted from this repository or retained in
  a disabled state. Depends on the skip-versus-fail decision above.
