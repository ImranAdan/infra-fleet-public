# Template readiness and advisor handoff

Reviewed 14 September 2026 against fleet `main` at `0ba8688`, fleet adoption PR
#37 at `10c492e`, and advisor capability PR #26 at `17920b7`. The tables describe
that review snapshot. Local fixes and integration candidates are pending remote
publication; none of these PRs was merged during this audit.

## Readiness decision

Infra Fleet has a usable local demonstration and a staging platform template.
The advisor can now review a clean local fleet checkout without a paid API or
cloud credentials. Development can focus on the advisor while the platform's
deployment gates remain explicit. This is not certification for a new public or
production deployment.

The public repositories keep no deployment credential. Static CI cannot prove
an actual AWS apply, canary promotion, rollback, or clean teardown. The retired
ingress-nginx path remains the largest deployment blocker. Rebranding does not
remove that technical dependency.

## Every open fleet PR

| PR | Review evidence | Disposition |
|---|---|---|
| [#37: plug-and-play adoption](https://github.com/ImranAdan/infra-fleet-public/pull/37) | Existing head has successful static, application, container, and policy checks. Two unresolved threads: the validator self-match is already fixed; the full-image Flux setter is still valid. | Local fix uses `:tag`, permits legitimate release/deployment version gaps, pins the previously floating VPC module, and updates the region attribute. Publish and resolve the threads with evidence before merge. |
| [#4: permanent AWS provider](https://github.com/ImranAdan/infra-fleet-public/pull/4) | Actual diff selects AWS `6.64.0`, despite the older PR title. No unresolved review threads. Old failure is missing AWS credentials. It merges cleanly into #37; backend-free, readonly-lock init, fmt, and validate pass. | Refresh against the adopted validation workflow and obtain current checks. A live plan is still needed before deploying the new provider. |
| [#8: staging dependency group](https://github.com/ImranAdan/infra-fleet-public/pull/8) | Selects EKS module `21.25.0`, AWS `6.64.0`, and Random `3.9.0`, plus a Cloudflare major upgrade. Old failure is missing AWS credentials. Conflicts with #37 in `main.tf` and the lockfile because Cloudflare was removed. | Prepared local integration retains the active updates and omits Cloudflare. Backend-free readonly-lock init and validate pass. Refresh the original PR after #37; do not restore an unused provider to settle the conflict. |
| [#14: IAM action scoping](https://github.com/ImranAdan/infra-fleet-public/pull/14) | No unresolved threads; old failure is missing AWS credentials. It conflicts with #37's IAM removal. Local integration retains parameterized OIDC trust, scoped actions, and both policy attachments while removing reintroduced S3/DynamoDB state permissions. Terraform validate passes; policy sizes are 4,267 and 2,310 characters. | Requires security review and a real apply/destroy cycle. It still grants powerful IAM writes and PassRole on broad resources; removing service wildcards does not establish least privilege. |

The old infrastructure failures were confirmed in runs `34531182314`,
`34531219978`, and `34532328885`: credential setup failed before Terraform plan.
They are not evidence that the provider or IAM changes passed or failed a plan.
Re-running the old branches against cloud-dependent workflows would not settle
their static compatibility.

## Every open advisor PR

| PR | Review evidence | Disposition |
|---|---|---|
| [#26: intent capability loop](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/26) | Existing head's quality checks pass. Two remaining valid findings: publication runs against a report containing twelve evaluations while the catalog has seventeen; closed capability issues miss lifecycle notes. | Local fixes wait for a current ratified report and reconcile deduplicated capability lifecycle notes for open and closed issues without changing state. New tests cover both. Regenerating an unapproved report in the publisher would bypass ratification. |
| [#27: advisory report](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/27) | Generated against fleet `0ba8688`; it covers the old twelve-position catalog and has no Quality check runs in the observed rollup. It does not describe #37 or the expanded cost intent. | Review only as a snapshot of that fleet and intent. After advisor changes merge, ratify a current report. Optional advisor-only App delivery is implemented locally to trigger PR checks; its event path still needs verification with configured credentials. |

## Changes that make first use practical

- Standardized the platform name to **Infra Fleet** in the entry points and
  documented the split between platform template and advisor product.
- Kept ECR account substitution intact through tag-only Flux image updates.
  The contract now allows release-please and Flux to advance at different times.
- Pinned VPC module `6.7.2`, the version resolved by the integration review.
  Terraform's provider lockfile does not pin module versions.
- Replaced deprecated `aws_region.id` with `aws_region.region`, as documented
  in the [AWS provider's region data source](https://github.com/hashicorp/terraform-provider-aws/blob/v6.64.0/website/docs/d/region.html.markdown).
- Added advisor `make review`, deterministic defaults, frozen dependency
  execution, ignored local output, and an explicit setup guide.
- Made capability and issue publication wait for current merged policy/intent.
  Full publication validation remains mandatory.
- Made fleet issue publication and feedback explicit opt-ins with
  `FLEET_ISSUES_ENABLED=true`. Existing configured installations need that value.
- Reused current-policy/intent/evidence eligibility validation in remediation.
  A dry run needs no fleet write credential; malformed fingerprints and forged
  accepted trade-offs fail before patching.
- Applied file budgets after policy/tracked-path filtering in Terraform and
  workflow collectors. Downloaded `.terraform` modules no longer displace
  tracked source; regression tests cover generated cache and ineligible files.
- Added optional advisor-only report App delivery. Both App secrets are needed
  together; bounded history preserves original workflow decisions and ignores
  unrelated authors.

## Verification performed locally

| Check | Result and limit |
|---|---|
| Advisor `make check` | Lint and formatting pass, strict mypy passes on 42 source files, 359 deterministic tests pass. |
| Advisor `make review` | JSON/Markdown produced against the clean integrated fleet checkout, using `stub`; fleet remains clean. Workflow and Deployment coverage are complete; IAM remains partial for two policy expressions the literal parser does not support. |
| Load Harness in Docker, Python 3.13 | 105 tests pass with `-W error`; cache placed outside the read-only source mount. |
| Fleet template contract | Passes; isolated simulations accept release-version advance and later deployment-tag advance and reject a full-image setter. |
| Actionlint | Advisor passes with ShellCheck. Fleet passes its configured syntax gate with ShellCheck disabled; enabling ShellCheck surfaces thirteen existing warnings across six workflows. |
| Yamllint | Fleet workflows/manifests and advisor workflows pass with the repositories' syntax-oriented configurations. |
| Terraform integration | Permanent and staging readonly-lock, backend-free init, fmt, and validate pass with #4/#8 and the reconciled #14. No AWS plan or apply. |
| Managed IAM policy quota | Both integrated rendered documents are below 6,144 characters; this checks size, not privilege safety. |
| Trivy 0.74.0 | Advisor dependency/secret scan and integrated permanent/staging configuration scans report no HIGH/CRITICAL findings under the existing fixture exclusions and staging ignore policy. |

The current changes do not alter container dependencies or controller charts.
Existing #37 container/schema/Kyverno CI evidence applies only to its recorded
head; updated PR heads must obtain fresh CI. No cloud workflow, report workflow,
GitHub App token, model API, public endpoint, or destructive action was executed
in this audit.

## Work to finish before public deployment

1. Publish the reviewed changes, obtain current PR checks, and resolve review
   threads before any merges. Land the adoption baseline before refreshing
   overlapping infrastructure updates.
2. Replace ingress-nginx through an approved Gateway API design and test real
   traffic analysis, canary promotion, rollback, optional TLS, and teardown in
   one private staging copy. See the existing deployment-preview notice.
3. Validate the narrower IAM policy through a complete apply/rebuild/destroy
   cycle. Derive resource scopes and missing actions from actual plan/API
   evidence; do not guess resource patterns or restore broad service wildcards.
4. Verify App-authored advisor report PRs receive required Quality checks and
   preserve decline history. Feedback policy PRs still use the default token
   and need a separate check-trigger solution.

## Advisor priorities after the template baseline

The next work belongs primarily in the advisor:

1. Ratify a report containing all seventeen current intent propositions and
   verify capability work is published only after that merge.
2. Expand deterministic check coverage for the declared positions. Cost has
   five positions and no registered checks. Absence of a finding is not evidence
   that a position is satisfied.
   The IAM literal parser also cannot currently evaluate the integrated
   policy's local condition references and quoted condition keys; it reports
   partial coverage. Add bounded structural support before treating such
   policies as evaluated, without introducing Terraform execution or cloud
   credentials into review.
3. Scope rollout intent to the workloads it means to cover. The remaining
   reliability finding points at Flux's generated `source-controller` using
   `Recreate`; do not mechanically edit upstream output to enforce an
   application availability rule.
4. Review recommendation identity for multiple affected resources. Aggregating
   evidence IDs into one fingerprint means fixing one resource can resolve the
   old grouped finding and create a new finding for the remaining resource.
   Report lifecycle language must not imply all affected resources were fixed.
5. Define an approved product requirement before supporting arbitrary private
   fleet copies. Current source labels, App targets, trusted repository checks,
   intent catalogs, and workflows are deliberately specific to this public MVP.

See [advisor integration](ADVISOR-INTEGRATION.md) and the advisor's
[setup guide](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/setup.md)
for the concrete local and optional automation paths.
