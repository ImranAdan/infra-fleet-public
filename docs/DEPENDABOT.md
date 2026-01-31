# Dependabot Configuration

**Status**: Active
**Last Updated**: 2025-12-25

Dependabot automatically creates pull requests to keep dependencies up to date and secure.

## Overview

Dependabot is configured to monitor four package ecosystems with **monthly** schedule and **grouped updates** to minimize PR noise and CI usage:

| Ecosystem | Directory | Schedule | Grouping |
|-----------|-----------|----------|----------|
| **pip** | `/applications/load-harness` | Monthly | All Python deps grouped |
| **docker** | `/applications/load-harness` | Monthly | Single PR |
| **github-actions** | `/` | Monthly | All actions grouped |
| **terraform** | `/infrastructure/staging`, `/infrastructure/permanent` | Monthly | Per-directory grouping |

**Why monthly + grouping?**
- Reduces PR noise (1 grouped PR vs 10+ individual PRs)
- Saves GitHub Actions minutes (fewer workflow runs)
- Still keeps dependencies reasonably up to date

## How It Works

1. **Scanning**: GitHub scans your dependency files on the configured schedule
2. **PR Creation**: When updates are available, Dependabot opens a pull request
3. **CI Validation**: Your existing CI workflows run on the PR
4. **Review & Merge**: You review the changes and merge when ready

## Pull Request Format

Dependabot PRs follow conventional commit format:

```
deps(python): bump flask from 2.3.0 to 2.3.1
deps(docker): bump python from 3.11-slim to 3.12-slim
ci: bump actions/checkout from 4.1.0 to 4.2.0
deps(terraform): bump hashicorp/aws from 5.30.0 to 5.31.0
```

## Configuration

The configuration lives in `.github/dependabot.yml`.

### Key Settings

- **Monthly schedule**: All ecosystems update monthly to reduce CI usage
- **Grouping**: All updates grouped per ecosystem into single PRs
- **PR limit**: Maximum 3 open PRs for pip ecosystem
- **Reviewers**: PRs are automatically assigned for review
- **Ignored**: GitHub Actions major versions, Python 3.14+

## Security Alerts

In addition to scheduled updates, Dependabot provides:

- **Security advisories**: Immediate alerts for known vulnerabilities
- **Priority PRs**: Security updates are created outside the normal schedule
- **CVSS scoring**: Vulnerabilities are rated by severity

View security alerts at: `Settings → Security → Dependabot alerts`

## Managing PRs

### Merge a Dependabot PR

```bash
# Via GitHub CLI
gh pr merge <pr-number> --squash

# Or use the GitHub UI
```

### Close Without Merging

Comment on the PR:
```
@dependabot close
```

### Ignore a Dependency Version

Comment on the PR:
```
@dependabot ignore this major version
@dependabot ignore this minor version
@dependabot ignore this dependency
```

### Rebase a PR

If the PR has conflicts:
```
@dependabot rebase
```

### Recreate a PR

If you want a fresh PR:
```
@dependabot recreate
```

## Workflow Integration

Dependabot PRs trigger the same CI workflows as regular PRs:

| Workflow | Runs On Dependabot PRs |
|----------|------------------------|
| `load-harness-ci.yml` | ✅ Yes (if app files change) |
| `infra-plan.yml` | ✅ Yes (if infra files change) |
| `commit-message-lint.yml` | ✅ Yes |
| `gitops-validate.yml` | ✅ Yes (if gitops files change) |

### Required Secrets

Dependabot PRs don't have access to regular repository secrets for security reasons. The following secrets must be added to **Dependabot secrets** (`Settings → Secrets → Dependabot`):

| Secret | Purpose |
|--------|---------|
| `AWS_GITHUB_ACTIONS_ROLE_ARN` | OIDC role for AWS authentication in Terraform plans |
| `TF_API_TOKEN` | HCP Terraform (Terraform Cloud) API token |

### Terraform Lockfile Handling

Dependabot updates module versions in `.tf` files but doesn't regenerate lockfiles. When a new module version requires a newer provider version than what's locked, `terraform init` would fail.

To handle this, `infra-plan.yml` uses `terraform init -upgrade` for Dependabot PRs:

```yaml
run: terraform init -input=false ${{ github.actor == 'dependabot[bot]' && '-upgrade' || '' }}
```

This allows the lockfile to be updated during CI when Dependabot updates modules.

## Best Practices

1. **Review changelogs**: Click through to release notes before merging
2. **Check CI status**: Ensure all checks pass before merging
3. **Batch minor updates**: Consider merging multiple minor/patch updates together
4. **Test major updates**: Major version bumps may have breaking changes
5. **Don't ignore security updates**: Prioritize security-related PRs

## Troubleshooting

### No PRs Being Created

1. Check if Dependabot is enabled: `Settings → Security → Dependabot`
2. Verify the schedule hasn't run yet (check Dependabot logs)
3. Confirm dependency files exist in the configured directories

### PR Has Conflicts

Comment `@dependabot rebase` to update the PR branch.

### Want to Pause Updates

Temporarily disable in `Settings → Security → Dependabot → Pause`

Or remove the ecosystem from `.github/dependabot.yml`.

## File Reference

| File | Purpose |
|------|---------|
| `.github/dependabot.yml` | Dependabot configuration |
| `applications/load-harness/requirements.txt` | Python dependencies |
| `applications/load-harness/Dockerfile` | Docker base image |
| `infrastructure/staging/*.tf` | Terraform providers |
| `infrastructure/permanent/*.tf` | Terraform providers |

## Related Documentation

- [RELEASE-ENGINEERING-ROADMAP.md](RELEASE-ENGINEERING-ROADMAP.md) - Phase 3: Dependency Management
- [GitHub Dependabot Documentation](https://docs.github.com/en/code-security/dependabot)
