# Security Policy

## This repository holds no credentials

`infra-fleet-public` is a template. It contains **no cloud credentials, no
deployment secrets, and no account identifiers**, and it is not named in any
IAM trust policy. Its CI validates code; it does not provision infrastructure.

That is a deliberate design decision, recorded in
[docs/CREDENTIALS-FREE-TEMPLATE-DDR.md](docs/CREDENTIALS-FREE-TEMPLATE-DDR.md).
The practical consequence is that `terraform plan`, `terraform apply` and any
workflow requiring AWS or HCP Terraform access cannot run here, by design.

If you are adopting this template, see [CONFIGURATION.md](CONFIGURATION.md).
Deployment happens in **your own private repository**, with **your own**
credentials.

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
- The absence of credentials causing workflows to fail. That is the intended
  behaviour, not a defect

## Notes for adopters

Two properties are worth preserving if you fork this:

**Do not add `pull_request_target`.** It runs with repository secrets in the
context of the base branch. Combined with checking out pull request code it is
the standard route to credential theft in a public repository. This template
does not use it anywhere.

**Do not use a wildcard in the OIDC trust subject.** A condition of
`repo:OWNER/REPO:*` matches every ref context, including pull requests. Pin it
to the specific branch or GitHub Environment that is allowed to deploy.
