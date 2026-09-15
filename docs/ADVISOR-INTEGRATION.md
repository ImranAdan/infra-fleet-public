# Connecting Infra Fleet Advisor

Infra Fleet provides the GitOps platform template and Load Harness. The
[advisor repository](https://github.com/ImranAdan/infra-fleet-advisor-public)
contains the review engine, owner intent, policy, reports, and delivery loop.
Platform deployment does not depend on the advisor.

The current advisor MVP reviews this public repository's desired state. It does
not inspect AWS, HCP Terraform, or Kubernetes, and it does not yet support
arbitrary/private adopter repositories as publication targets.

## Review without deploying

Keep clean copies of both repositories alongside one another:

```bash
git clone https://github.com/ImranAdan/infra-fleet-public.git
git clone https://github.com/ImranAdan/infra-fleet-advisor-public.git
cd infra-fleet-advisor-public
make setup
make review
```

Requires Git, Python 3.11+, `uv`, and Make. Read `review-output/report.md` in the
advisor checkout. The review is deterministic by default and uses the fleet's
full HEAD SHA. Dependency installation needs internet access; analysis reads
only the local checkout.

The advisor rejects a dirty fleet checkout and keeps output outside it. Changes
in an open fleet PR are evaluated only when its exact clean commit is checked
out locally; scheduled reviews target merged fleet `main`.

## Delivery contract

1. The advisor compiles declared intent into registered deterministic checks.
2. It records collected evidence, incomplete coverage, and unverified intent.
3. Its advisory workflow proposes a report PR in the advisor repository.
4. A reviewer examines and merges the report-only PR. That PR is the
   issue-creation decision record and the report becomes the lifecycle baseline.
5. A separate configured issues-only workflow verifies that approval,
   revalidates its exact report and creates eligible fleet issues. Each new
   issue links to the approving report PR. Unsupported intent and incomplete
   relevant collection remain report coverage rather than fresh fix requests.
6. The owner selects valuable fleet issues and asks an agent working in this
   project to propose PR fixes. Issue creation does not automatically start an
   agent. Fleet review and CI govern the proposed changes.
7. Another advisor run checks the resulting repository state. Existing issue
   identities are reused and resolution notes leave closure to a maintainer.

The optional manual mechanical remediation path remains separate from this
ordinary agent handoff; opening a fleet proposal needs a write credential.

The fleet grants no advisor access to its cloud account. Human decisions control
issue closure, policy approval, and fleet merges. See the advisor's
[setup guide](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/setup.md)
for opt-in variables, credential scopes, report freshness, and current limits.
See [the operating workflow](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/WORKFLOW.md)
for review, publication retries and selecting agent work.

## Platform contracts to retain

Keep cloud-specific runtime values outside Git and retain Flux substitutions in
profile overlays. The AWS adapter translates `${ECR_REGISTRY}` into the shared
`${IMAGE_REGISTRY}` contract, while image automation changes only the AWS
overlay tag. The release manifest and deployed tag can differ while a release
builds and Flux reconciles; neither is evidence of a failed deployment.

The advisor is supplementary static review. Platform CI remains responsible
for Terraform, manifest, policy, application, and container checks. A live
apply, rollout, rollback, and destroy cycle is required to validate an adopted
deployment. The ingress-nginx replacement and remaining IAM scoping are tracked
in [template readiness](TEMPLATE-READINESS.md).
