# Security Policy

## Known deployment limitation

The current progressive-delivery path depends on the retired community
`ingress-nginx` controller. Upstream no longer provides bug or security fixes.
Do not expose a new public deployment as production infrastructure. Replacing
the Ingress/NGINX metric path with a maintained Gateway API implementation
requires an apply, canary rollout, rollback, and destroy validation cycle; it
is not treated as a mechanical dependency bump.

## Deployment scope

`infra-fleet-public` is a staging platform template. For deployment setup and
operational prerequisites, see [CONFIGURATION.md](CONFIGURATION.md).
The architectural rationale is recorded in
[Template Deployment Boundaries](docs/PUBLIC-TEMPLATE-BOUNDARY-DDR.md).

## Reporting a vulnerability

Report security issues through GitHub's private vulnerability reporting on
this repository rather than opening a public issue.

Please include the affected file or workflow, what an attacker could achieve,
and the conditions required. A working reproduction is helpful but not
required.

## Scope

In scope:

- Anything in this repository that would let a fork, a pull request, or a
  third party obtain credentials or execute code with elevated privilege
- IAM policies, trust conditions, and Kubernetes manifests that grant more
  than the documentation claims
- Workflow triggers that expose secrets to untrusted input

Out of scope:

- Vulnerabilities in a deployment you built from this template using your own
  credentials and configuration
- Findings in upstream projects (EKS, Flux, Flagger, Prometheus) that this
  template merely uses
- Setup failures caused by incomplete deployment configuration

## Notes for adopters

Two properties are worth preserving if you fork this:

**Do not add `pull_request_target`.** It runs with repository secrets in the
context of the base branch. Combined with checking out pull request code it is
the standard route to credential theft in a public repository. This template
does not use it anywhere.

**Do not use a wildcard in the OIDC trust subject.** A condition of
`repo:OWNER/REPO:*` matches every ref context, including pull requests. Pin it
to the specific branch or GitHub Environment that is allowed to deploy.
