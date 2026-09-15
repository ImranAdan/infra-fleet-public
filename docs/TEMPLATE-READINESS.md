# Template readiness and advisor handoff

Reviewed 15 September 2026. The adoption baseline, dependency updates, IAM
action scoping, public messaging, advisor delivery fixes and explicit local/AWS
deployment profiles have landed. The platform is ready for a fresh advisor
review of the merged desired state. It remains a staging template with explicit
deployment gates.

## Readiness decision

Infra Fleet provides a local Docker demonstration and a fully exercised local
Kubernetes profile alongside the inspectable AWS staging profile. Infra Fleet
Advisor reviews a verified Git checkout using deterministic collectors and a
default stub synthesizer, then proposes recommendations for human review.
Development can now focus primarily on the advisor.

The local cluster has proved Git delivery, policy enforcement, network
isolation, monitoring, canary promotion and forced rollback. Static CI still
does not prove an AWS apply, rollout, rollback or clean teardown. Retired
ingress-nginx remains an AWS deployment blocker; the local profile uses Envoy
Gateway instead.

## PR closeout

| Repository and PR | Result |
|---|---|
| Fleet [#37](https://github.com/ImranAdan/infra-fleet-public/pull/37) | Merged the adoption baseline: tag-only Flux updates preserve account substitution, release and deployment tags may advance independently, VPC is pinned, and setup and advisor integration are documented. |
| Fleet [#38](https://github.com/ImranAdan/infra-fleet-public/pull/38) | Merged the Load Harness release to `1.6.5`; the deployment tag may legitimately lag until GitOps advances it. |
| Fleet [#4](https://github.com/ImranAdan/infra-fleet-public/pull/4) and [#40](https://github.com/ImranAdan/infra-fleet-public/pull/40) | Merged AWS `6.64.0`, Random `3.9.1` and EKS module `21.25.0` after current validation. Superseded staging PR [#8](https://github.com/ImranAdan/infra-fleet-public/pull/8) was closed; the removed Cloudflare provider was not restored. |
| Fleet [#39](https://github.com/ImranAdan/infra-fleet-public/pull/39) | Merged the pinned Flux installer action update; the requested Flux CLI version remains pinned separately. |
| Fleet [#14](https://github.com/ImranAdan/infra-fleet-public/pull/14) | Reconciled and merged IAM action scoping while retaining parameterized OIDC trust and removing obsolete state permissions. Powerful IAM writes and broad resource scopes remain; this is an improvement rather than proof of least privilege. |
| Fleet [#41](https://github.com/ImranAdan/infra-fleet-public/pull/41) | Merged the public messaging rebrand. Entry points describe platform value and operator setup; architectural discussion of credential boundaries belongs in the design record. |
| Advisor [#26](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/26) | Merged deterministic local setup, current-report publication gates, capability lifecycle handling, opt-in fleet publication, remediation eligibility checks, collector budgets and a bounded IAM literal parser. All review threads were resolved. |
| Advisor [#28](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/28) | Merged matching public messaging and a recorded language decision. |
| Advisor [#29](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/29) | Preserves historical evidence behind lifecycle notes while using current facts for freshly validated recommendations. Publication validation remains mandatory. |
| Advisor [#27](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/27) | Merged the report against the adopted fleet and all seventeen intent positions. Its earlier automatic capability-ticket publication is superseded by the report-approval decision in PDR 0006. |
| Fleet [#46](https://github.com/ImranAdan/infra-fleet-public/pull/46) | Adds the `./fleet` facade, explicit local and AWS Flux roots, shared application and controller bases, provider-specific routing, registry policies and canary metrics, plus a real local acceptance workflow. |

## Verification and its limits

| Check | Evidence and limit |
|---|---|
| Advisor quality | The report-approval handoff passes Ruff, formatting, strict mypy on 43 source files and all 443 deterministic tests, including publication freshness races. |
| Advisor local review | JSON and Markdown are produced from the verified merged fleet with `stub`. Workflow and Deployment collection are complete. IAM collection is explicitly partial for four unsupported policy resources or expressions; it does not execute Terraform or fetch policy URLs. |
| Publication plan | The approved report validates one active fleet recommendation and one resolution action. Two historical IAM recommendations are deferred because their current collector is incomplete. Every new issue links to the approving report PR; unknown intent remains coverage without automatic advisor tickets. |
| Load Harness | All 112 tests pass in the container with deprecation warnings treated as errors, alongside container and image-security checks. |
| Local Kubernetes | A real kind cycle passed Flux drift repair, Kyverno negative cases, Calico isolation, Prometheus discovery, healthy canary promotion and forced-failure rollback. Authenticated app/UI, Grafana and Prometheus smoke checks also passed. |
| Deployment profiles | Both effective roots render; 81 resources pass Kubernetes 1.35 schema checks, 20 policy regression cases pass, and each profile's policies accept its rendered resources. AWS was not invoked. |
| Template contract | CI passes. Isolated checks accept release/deployment tag advances and reject a full-image Flux setter. |
| Infrastructure | Current permanent and staging validation and scans pass. Backend-free, readonly-lock initialization and Terraform validation were exercised locally. No live AWS plan or infrastructure change was performed. |
| IAM policy quota | The reviewed rendered documents fit within the 6,144-character managed-policy quota. This establishes size compatibility, not privilege safety. |
| Workflow checks | Advisor Actionlint passes with ShellCheck. Fleet passes its configured syntax gate; enabling ShellCheck surfaces thirteen existing warnings across six workflows. |
| Main CI | Applicable post-merge workflows were checked through completion. The optional infrastructure apply job remained gated; successful static workflows do not establish deployment success. |

Approved report [#47](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/47)
triggered the App-authenticated publisher and created fleet issue
[#44](https://github.com/ImranAdan/infra-fleet-public/issues/44). A retry created
zero duplicates. No paid model API or live cluster validation was performed.
Fleet issue publication is enabled for this approved-report handoff through
`FLEET_ISSUES_ENABLED=true`. Optional decision feedback has a separate
`FLEET_FEEDBACK_ENABLED=true` setting. The report PR is the fleet issue-creation
decision record. The earlier generated advisor tickets are consolidated in a
[coverage review](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/COVERAGE-REVIEW.md);
closing those tickets does not mean their missing checks are implemented.

## Work before public deployment

1. Replace ingress-nginx through an approved Gateway API design and test real
   traffic analysis, canary promotion, rollback, optional TLS and teardown in
   one private staging copy. Retain the deployment-preview notice until this
   cycle succeeds.
2. Validate the narrower IAM policies through a complete apply, rebuild and
   destroy cycle. Derive missing actions and resource scopes from actual
   plan/API evidence instead of restoring service wildcards.
3. Verify optional App-authored report PRs receive required Quality checks and
   preserve decline history. Default-token automated report updates did not
   obtain completed Quality checks in this audit; use a maintainer-reviewed
   check-trigger path before merging. Feedback policy PRs require their own
   solution.

## Advisor priorities

1. Select deterministic check work deliberately from report coverage. Cost has
   five positions and no registered checks. Absence of a finding does not prove
   that an intent position is satisfied.
2. Expand bounded IAM structural support for local condition references and
   interpolated resource ARNs. Keep unsupported policy data explicitly partial;
   do not execute Terraform or introduce cloud access into collection.
3. Scope rollout intent to the workloads it means to cover. The
   [application rollout contract](ROLLOUT-CAPACITY.md) enforces zero unavailable
   capacity across the Load Harness HPA range and preserves generated controller
   semantics. The remaining
   reliability finding points at Flux's generated `source-controller` using
   `Recreate`; do not mechanically edit upstream output to enforce an
   application availability rule.
4. Improve recommendation identity for multiple affected resources. Fixing one
   resource can resolve an old grouped fingerprint and create a new fingerprint
   for the remaining resource. That lifecycle transition does not mean all
   affected workloads were fixed.
5. Define an approved product requirement before supporting arbitrary private
   fleet copies. Source labels, App targets, trusted repository checks, intent
   catalogs and workflows currently target this one public fleet.

See [advisor integration](ADVISOR-INTEGRATION.md), the
[deployment boundary design record](PUBLIC-TEMPLATE-BOUNDARY-DDR.md), and the
advisor [setup guide](https://github.com/ImranAdan/infra-fleet-advisor-public/blob/main/docs/setup.md)
for the concrete local and optional automation paths.
