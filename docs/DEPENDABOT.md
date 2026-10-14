# Dependabot

`.github/dependabot.yml` checks these dependency surfaces every month:

| Ecosystem | Directory | Update behavior |
|---|---|---|
| Python | `/applications/load-harness` | grouped |
| Python | `/` (development tools) | grouped |
| Docker | each `/applications/<app>` and `/platform/local/git-server` | one update stream per directory |
| GitHub Actions | workflows and `.github/actions/*` | grouped by action across directories, including major versions |
| Terraform | `/infrastructure/staging` and `/infrastructure/permanent` | grouped per stack |

Dependabot cannot read Flux `HelmRelease` chart versions or the generated Flux
manifest (`k8s/flux-system/flux-system/gotk-components.yaml`). The **Chart
Freshness** workflow is their monthly check instead:
`scripts/check-chart-versions.py` compares each chart with its `HelmRepository`
(HTTP `index.yaml` or OCI tags) and Flux with its latest release, writes a table
to the run summary, and fails when anything is behind. Bump the chart in its
`HelmRelease`, or, when a version is deliberately kept, add it to the script's
`HELD` table with the issue that holds it. A hold names the exact pinned version,
so it lapses as soon as that pin changes.

Reviewers, labels, and assignees can be configured for your deployment
repository. Dependency updates arrive as ordinary pull requests for review.

## CI behavior

Dependabot pull requests use the same static checks as other pull
requests:

- Python tests and container scanning when application dependencies change;
- Terraform formatting, `init -backend=false`, validation, and Trivy
  configuration scanning when a stack changes;
- manifest and policy validation when GitOps dependencies change; and
- commit-message and workflow validation.

Do **not** create Dependabot copies of `AWS_GITHUB_ACTIONS_ROLE_ARN` or
`TF_API_TOKEN`. Pull request validation neither needs nor receives deployment
credentials.

GitHub Actions references are pinned to full commit SHAs with readable version
comments. Dependabot scans workflows and repository composite actions, and can
update every reference to a given action together. Major versions remain
eligible because the immutable pin and normal template, workflow and intent
gates make the runtime change explicit and reviewable. Different actions may
need separate PRs; the one-open-PR limit serializes them so action upgrades
cannot create a CI queue. Container bases use a readable tag plus a digest so
an update is reviewable and the build remains immutable between updates.

## Terraform lock files

Terraform validation honours committed provider lock files; CI does not
silently run `terraform init -upgrade`. If a dependency update requires a lock
change, regenerate it deliberately with the supported Terraform version,
review the provider checksums, and commit it in the same pull request.

## Repository settings

Version-update configuration does not itself enable GitHub's dependency graph,
Dependabot alerts, or security-update pull requests. A template owner should
review those settings under **Settings → Code security** after creating the
private repository. Their state cannot be declared reliably by this file.

See the [GitHub Dependabot documentation](https://docs.github.com/en/code-security/dependabot)
for repository-level controls.
