# Dependabot

`.github/dependabot.yml` checks four dependency surfaces every month:

| Ecosystem | Directory | Update behavior |
|---|---|---|
| Python | `/applications/load-harness` | grouped |
| Docker | `/applications/load-harness` | one update stream |
| GitHub Actions | `/` | grouped; major-version jumps ignored |
| Terraform | `/infrastructure/staging` and `/infrastructure/permanent` | grouped per stack |

No reviewer, label, assignee, repository owner, or cloud credential is baked
into the template. A fork receives ordinary pull requests for a human to
review.

## CI behavior

Dependabot pull requests use the same credentials-free checks as other pull
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
comments. Dependabot can update both together. Container bases use a readable
tag plus a digest so an update is reviewable and the build remains immutable
between updates.

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
