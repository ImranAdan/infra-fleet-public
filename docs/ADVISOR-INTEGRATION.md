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
full HEAD SHA. It requires no cloud credential or model API key. Dependency
installation needs internet access; analysis reads only the local checkout.

The advisor rejects a dirty fleet checkout and keeps output outside it. Changes
in an open fleet PR are evaluated only when its exact clean commit is checked
out locally; scheduled reviews target merged fleet `main`.

## Delivery contract

1. The advisor compiles declared intent into registered deterministic checks.
2. It records collected evidence, incomplete coverage, and unverified intent.
3. Its advisory workflow proposes a report PR in the advisor repository.
4. A maintainer reviews and merges the report before it becomes the baseline.
5. Optional issues-only publication revalidates that baseline before creating
   fleet issues. Unsupported intent becomes capability work in the advisor.
6. A separate manual remediation path previews the narrow mechanical patcher
   registry; opening a fleet proposal needs a separate write credential.

The fleet grants no advisor access to its cloud account. Human decisions control
issue closure, policy approval, and fleet merges. See the advisor's
[setup guide](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/setup.md)
for opt-in variables, credential scopes, report freshness, and current limits.

## Platform contracts to retain

Keep cloud-specific runtime values outside Git and retain Flux substitutions in
manifests. Image automation uses the `:tag` setter so it preserves
`${ECR_REGISTRY}`. The release manifest and deployed tag can differ while a
release builds and Flux reconciles; neither is evidence of a failed deployment.

The advisor is supplementary static review. Platform CI remains responsible
for Terraform, manifest, policy, application, and container checks. A live
apply, rollout, rollback, and destroy cycle is required to validate an adopted
deployment. The ingress-nginx replacement and remaining IAM scoping are tracked
in [template readiness](TEMPLATE-READINESS.md).
