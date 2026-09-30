# Template readiness

[Documentation index](README.md) · [Security policy](../SECURITY.md) ·
[Deployment profiles](DEPLOYMENT-PROFILES.md)

Reviewed 30 September 2026.

Infra Fleet is ready to use as a local Kubernetes platform template and as an
inspectable AWS staging implementation. It is not presented as a production
platform. The local profile is exercised end to end; the AWS profile is
validated statically and still needs a complete account-specific lifecycle.

## Current evidence

| Area | Evidence | Boundary |
|---|---|---|
| Application contract | Every included contract renders through both profiles; CI rejects platform files that name an app | A new app still needs its own image build and live acceptance evidence |
| Local Kubernetes | Flux drift repair, admission, namespace isolation, monitoring, on-demand app launch/removal, serial canary promotion, forced rollback and teardown run on kind | This proves the pinned local stack on GitHub-hosted runners and the supported workstation path |
| Kubernetes manifests | Both effective roots pass Kustomize rendering, Kubernetes 1.35 schema checks, Kyverno policy tests and profile contract tests | Static rendering does not prove a cloud controller or public endpoint |
| Application | Unit tests, a container smoke test and a fixed-vulnerability image scan run in CI | Load Harness is a sample workload rather than a production SLO claim |
| Infrastructure | Terraform formatting, initialization, validation and configuration scanning pass for permanent and staging stacks | No live AWS plan or apply is performed on ordinary pull requests |
| Change governance | Exact-head CI, the advisor intent gate, review-thread checks and the merge gate govern pull requests | Intent, merge authority, IAM, credentials, migrations and permanent infrastructure remain owner decisions |
| Advisor | Deterministic collectors review a clean Fleet commit and approved reports can create Fleet issues; registered remediation still passes Fleet gates | The advisor does not inspect a live AWS account, HCP Terraform or a Kubernetes cluster |

The long local workflow runs for pull requests that change runtime paths, on
demand, and weekly against `main`. It records the exact commit in the `local`
GitHub Environment and tears the cluster down. Fast pull-request checks remain
the first feedback path.

## Remaining AWS acceptance

Before treating the AWS profile as a public deployment path, run one complete
cycle in a private adopter repository:

1. apply the permanent and staging Terraform stacks using the documented OIDC
   path;
2. publish the selected application image and let Flux reconcile EKS;
3. verify the NLB, DNS, Let's Encrypt certificate and HTTPS Gateway route;
4. observe a healthy canary promotion and a forced rollback through the
   Gateway metrics; and
5. destroy staging, then confirm that load balancers, volumes and other
   billable staging resources are gone while the permanent OIDC/ECR foundation
   remains.

Use [Configuration](../CONFIGURATION.md) for onboarding, [GitHub
Environments](GITHUB-ENVIRONMENTS.md) for deployment evidence, and [AWS cost
controls](COST-OPTIMIZATION-GUIDE.md) for the resource and teardown model.

## Advisor handoff

The advisor reads merged desired state. Its report PR is the reviewable
decision record for issue creation; after that report merges, a separate
issues-only workflow publishes eligible findings to this repository. A finding
is useful work only after it points at current evidence and survives the
advisor's freshness and coverage checks. See [Advisor
integration](ADVISOR-INTEGRATION.md) for the complete delivery loop.
