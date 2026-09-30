# Multi-environment promotion proposal

[Documentation index](README.md) · [Deployment profiles](DEPLOYMENT-PROFILES.md)

Status: deferred product design. Updated 30 September 2026.

Infra Fleet currently supports two explicit targets:

| Target | Purpose | State |
|---|---|---|
| `local` | Development and full platform acceptance on kind | Implemented and live-tested |
| `aws-staging` | Private account-specific EKS evaluation | Implemented as a deployment preview; live AWS lifecycle outstanding |

There is no production profile, production Terraform state, production GitHub
Environment or promotion workflow. Adding one is a product decision rather
than a rename of staging.

## Constraints a production design must preserve

- **One application contract.** The platform and profiles consume the same
  contract; an environment overlay cannot embed an application name.
- **Immutable promotion.** Staging and production must identify the same image
  digest or immutable release artifact. Promotion must not rebuild it.
- **Isolated state and identity.** Each cloud environment needs its own state,
  OIDC trust, deployment protection and least-privilege AWS role. The current
  `staging` Environment name is part of the existing OIDC subject.
- **Git as desired state.** Environment selection and version promotion must be
  reviewable changes reconciled by that environment's Flux installation.
- **Independent rollback.** A failed production rollout must not change the
  tested staging revision, and database migrations need a separately declared
  compatibility and rollback policy.
- **Explicit cost ownership.** A continuously available production control
  plane, network and worker fleet needs a budget, availability target,
  operational owner and teardown/retention policy before implementation.

## Decisions still required

1. Whether to reuse Terraform modules directly or introduce another composition
   layer. Terragrunt is an option, not an accepted dependency.
2. The account and network isolation model for staging and production.
3. The artifact promotion record and who may approve the production GitHub
   Environment.
4. Secret delivery, rotation and break-glass access for a long-lived target.
5. Data migration, backup, recovery and regional availability requirements.
6. Which live acceptance evidence is required before a staging artifact can be
   promoted.

Do not copy the staging stack into a `production` directory until these choices
are recorded. The current implementation remains authoritative in
[`k8s/profiles`](../k8s/profiles), [`infrastructure`](../infrastructure), and
the [GitHub Environment guide](GITHUB-ENVIRONMENTS.md).
