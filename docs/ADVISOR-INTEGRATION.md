# Connecting Infra Fleet Advisor

Infra Fleet provides the GitOps platform template and Load Harness. The
[advisor repository](https://github.com/ImranAdan/infra-fleet-advisor-public)
contains the review engine, owner intent, policy, reports, and delivery loop.
Platform deployment does not depend on the advisor.

The current advisor MVP reviews this public repository's desired state. It does
not inspect AWS, HCP Terraform, or Kubernetes, and it does not yet support
arbitrary/private adopter repositories as publication targets.

## Intent gate on pull requests

`.github/workflows/intent-gate.yml` runs the advisor's checks on every pull
request to `main`. It compares the merge result with its base and fails when the
change would newly diverge from a declared position, or make one the advisor
could evaluate unevaluable. The job summary lists the evidence. It holds only
`contents: read`, calls no model, and publishes nothing. The job is defined once
in `.github/workflows/intent-gate-run.yml`, where the advisor action is pinned by
commit SHA, so upgrading it is a normal one-line reviewed change here.

A deliberate exception needs an owner-approved intent or policy change in the
advisor first; the gate never weakens intent to let a change through.

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

## Coverage on the dashboard

Grafana's **Fleet Application** dashboard ends with a **Declared intent** row
fed by the advisor's latest accepted report (`reports/report.json` on the
advisor's `main`): how many positions are declared, how many evidence decides,
how many are satisfied or divergent, which fleet commit was reviewed and when,
and the divergent positions. It sits under the live golden signals, so what the
fleet declares and how it is running are read together. See
[monitoring](MONITORING-SETUP.md#declared-intent-next-to-live-signals).

## Delivery contract

1. The advisor compiles declared intent into registered deterministic checks.
2. It records collected evidence, incomplete coverage, and unverified intent.
3. Its advisory workflow proposes a report PR in the advisor repository.
4. The trusted autonomous worker merges the report-only PR only after
   `Advisor Quality`, the isolated `Advisor Gates` job and the exact-head merge
   gate pass. `Advisor Gates` contains the drills, ratchet, workflow lint and
   security scan. Remove the marker to hold the PR; close it to decline that
   material report. The merge is the issue-creation decision record and
   lifecycle baseline.
5. A separate configured issues-only workflow verifies that merge,
   revalidates its exact report and creates eligible fleet issues. Each new
   issue links to the report PR. Unsupported intent and incomplete
   relevant collection remain report coverage rather than fresh fix requests.
6. Registered deterministic patchers run in a read-only planning job and may
   open an opted-in Fleet PR through a separate Fleet-owned write job. The job
   explicitly dispatches bounded validation on that exact branch because
   `GITHUB_TOKEN` PR creation suppresses ordinary PR events. Other issues wait
   for a coding-agent runtime. Fleet CI, the intent gate and the merge gate
   govern every proposed change. Dispatched intent evidence counts only for the
   registered `advisor/remediation` branch. The write job rechecks that Fleet
   main still equals the report commit before it applies the bounded patch.
7. Another advisor run checks the resulting repository state. Existing issue
   identities are reused and resolution notes leave closure to a maintainer.

Mechanical remediation remains separate from analysis. Advisor code receives no
Fleet write token; the Fleet workflow owns PR creation with `GITHUB_TOKEN`.
No report-delivery App or cross-repository contents token is required.

The Fleet grants no advisor access to its cloud account. The owner still controls
issue closure, policy and intent changes, credentials, IAM, permanent
infrastructure, migrations and merge authority. See the advisor's
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
deployment. The AWS live cycle of the Gateway route and remaining IAM scoping are tracked
in [template readiness](TEMPLATE-READINESS.md).
