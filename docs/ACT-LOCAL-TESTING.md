# Local GitHub Actions Testing with `act`

## Overview

This project uses [`act`](https://github.com/nektos/act) to test GitHub Actions workflows locally before pushing to GitHub. This enables faster iteration and prevents broken workflows from being committed.

> **Important**: `act` is a local development tool with significant limitations. Many workflows in this repository use OIDC authentication for AWS access and **cannot be tested locally**. For these workflows, you must use the proper CI/CD process via pull requests. See [OIDC Limitations](#oidc-limitations) for details.

## Installation

### macOS (Homebrew)
```bash
brew install act
```

### Linux
```bash
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash
```

### Windows (Chocolatey)
```bash
choco install act-cli
```

## Quick Start

### List Available Workflows
```bash
act -l
```

This shows all workflows and jobs in the repository.

**Jobs you CAN test locally** (no AWS/OIDC required):
| Job | Workflow | Description |
|-----|----------|-------------|
| `validate-workflows` | validate-workflows.yml | Validates YAML syntax |
| `test` | load-harness-ci.yml | Flask app unit tests |
| `docker-build` | load-harness-ci.yml | Docker image build and test |
| `security-scan` | load-harness-ci.yml | Trivy security scanning |

**Jobs you CANNOT test locally** (require OIDC - use PR process):
| Job | Workflow | Description |
|-----|----------|-------------|
| `push-to-ecr` | load-harness-ci.yml | Push images to ECR |
| `pre-verification`, `cleanup-kubernetes`, `terraform-destroy`, `final-report` | nightly-destroy.yml | Nightly infrastructure teardown |
| `health-check`, `build-infrastructure`, `verify-cluster`, `verify-flux` | rebuild-stack.yml | Infrastructure rebuild |
| `plan-staging`, `plan-permanent` | infra-plan.yml | Terraform plan |
| `apply` | infra-apply.yml | Terraform apply |
| All jobs | flux-validate.yml, verify-cluster.yml | Cluster verification |

### Run a Specific Workflow

```bash
# Validate all workflows
act -j validate-workflows --container-architecture linux/amd64

# Test Flask application
act -j test --container-architecture linux/amd64

# Build Docker image
act -j docker-build --container-architecture linux/amd64
```

### Dry Run (Check Without Executing)
```bash
act -j validate-workflows --container-architecture linux/amd64 -n
```

## Configuration

### Platform Architecture

On Apple M-series chips, always use the `--container-architecture linux/amd64` flag to avoid compatibility issues:

```bash
act -j <job-name> --container-architecture linux/amd64
```

## OIDC Limitations

Most infrastructure workflows in this repository use **OIDC (OpenID Connect) authentication** to securely access AWS without storing long-lived credentials. This is a security best practice, but it means these workflows **cannot run locally**.

### Why OIDC Workflows Can't Run Locally

OIDC authentication works by:
1. GitHub Actions requests a short-lived token from GitHub's identity provider
2. AWS trusts GitHub's identity provider and issues temporary credentials
3. The workflow uses these credentials to access AWS resources

**`act` cannot provide this** because it doesn't have access to GitHub's identity provider. There is no workaround - you cannot simulate OIDC locally.

### Workflows Requiring OIDC

The following workflows require OIDC and **must be tested via pull requests**:

| Workflow | Purpose |
|----------|---------|
| `nightly-destroy.yml` | Scheduled infrastructure teardown |
| `rebuild-stack.yml` | Manual infrastructure rebuild |
| `infra-plan.yml` | Terraform plan on PR |
| `infra-apply.yml` | Terraform apply on merge |
| `flux-validate.yml` | Flux configuration validation |
| `verify-cluster.yml` | EKS cluster health checks |
| `test-destroy-cleanup.yml` | Test environment cleanup |
| `load-harness-ci.yml` (`push-to-ecr` job only) | ECR image push |

### The Correct Process for OIDC Workflows

**Do not attempt to run these locally.** Instead:

1. **Create a pull request** with your changes
2. **GitHub Actions runs automatically** with proper OIDC authentication
3. **Review the workflow output** in the GitHub Actions tab
4. **Iterate on the PR** if changes are needed
5. **Merge when CI passes** - this is the only way to test these workflows

This PR-based workflow ensures:
- Proper authentication without exposing credentials
- Audit trail of all infrastructure changes
- Code review before infrastructure modifications
- Consistent, reproducible environments

## Workflow Validation Results

When you run `act -j validate-workflows`, it checks:

✅ **YAML Syntax** - All workflow files are syntactically valid
✅ **Required Secrets** - Documents which AWS secrets are needed
✅ **Cron Schedules** - Validates scheduled workflow timing
✅ **Safety Checks** - Confirms destructive operations have safeguards

## Common Use Cases

### Before Committing Workflow Changes
```bash
# Validate syntax before pushing
act -j validate-workflows --container-architecture linux/amd64
```

### Testing Application CI
```bash
# Run full CI pipeline locally
act push --container-architecture linux/amd64
```

### Debugging Workflow Issues
```bash
# Verbose output for troubleshooting
act -j <job-name> --container-architecture linux/amd64 --verbose
```

## Docker Requirements

`act` requires Docker to be running. If you get connection errors:

1. **macOS**: Start Docker Desktop
2. **Linux**: `sudo systemctl start docker`
3. **Windows**: Start Docker Desktop

Verify Docker is running:
```bash
docker ps
```

## Developer Workflow

### What Developers CAN Test Locally

✅ **Application Code**:
```bash
# Local development with hot reload
cd applications/load-harness
docker-compose up --build

# Run tests
docker-compose --profile test run test
```

✅ **Workflow Validation**:
```bash
# Validate GitHub Actions syntax
act -j validate-workflows --container-architecture linux/amd64

# Test application CI pipeline
act -j test --container-architecture linux/amd64
act -j docker-build --container-architecture linux/amd64
```

### What Developers CANNOT Test Locally

❌ **Infrastructure workflows** - Require OIDC authentication (see [OIDC Limitations](#oidc-limitations))
❌ **AWS deployments** - Must go through PR process for proper authentication
❌ **ECR image pushes** - The `push-to-ecr` job requires OIDC
❌ **Flux GitOps sync** - Happens automatically in the cluster after merge

**Important**: Developers work entirely with Docker locally. No AWS credentials or EKS access needed for daily development. When you need to test infrastructure or deployment workflows, **create a pull request** - this is the intended workflow, not a limitation.

## Limitations

### Workflows That Can't Run Locally

Some workflows cannot run with `act` due to OIDC requirements:

- **All infrastructure workflows** - `nightly-destroy.yml`, `rebuild-stack.yml`, `infra-plan.yml`, `infra-apply.yml`
- **Cluster verification** - `flux-validate.yml`, `verify-cluster.yml`, `test-destroy-cleanup.yml`
- **ECR pushes** - The `push-to-ecr` job in `load-harness-ci.yml`
- **Scheduled workflows** (cron) - Can test job logic locally, but not the schedule trigger
- **workflow_dispatch** - Manual triggers work with `--eventpath` flag

See [OIDC Limitations](#oidc-limitations) for details on why and what to do instead.

### Differences from GitHub Actions

- Different runner images (catthehacker/ubuntu vs GitHub's runners)
- Some GitHub-specific features may not work identically
- Secrets must be provided via `--secret-file` or environment variables

## Additional Workflows

This repository also includes these workflows not covered above:

| Workflow | Purpose | Can Run Locally |
|----------|---------|-----------------|
| `commit-message-lint.yml` | Validates commit message format | ✅ Yes |
| `gitops-validate.yml` | Validates GitOps manifests | ✅ Yes |
| `release-please.yml` | Automated release management | ❌ No (GitHub API) |

## Troubleshooting

### "Cannot connect to Docker daemon"
- Start Docker Desktop/daemon
- Check Docker is running: `docker ps`

### "Workflow is not valid"
- Run validation: `act -j validate-workflows --container-architecture linux/amd64`
- Check YAML syntax in the affected workflow file

### "Error: Job failed"
- Check logs for specific error messages
- Verify secrets are configured if needed
- Ensure Docker has enough resources (CPU/memory)

### Platform Architecture Warnings
- Always use `--container-architecture linux/amd64` on M-series Macs
- This prevents ARM/x86 compatibility issues

## Best Practices

1. **Always validate before committing**
   ```bash
   act -j validate-workflows --container-architecture linux/amd64
   ```

2. **Test locally before pushing**
   - Faster feedback loop
   - Prevents CI failures
   - Saves GitHub Actions minutes

3. **Never commit secrets**
   - Configure GitHub secrets for production workflows
   - Infrastructure workflows use OIDC (no local secrets needed)

4. **Use dry-run for exploration**
   ```bash
   act -n  # Shows what would run without executing
   ```

## Resources

- [act Documentation](https://github.com/nektos/act)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Workflow Syntax Reference](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions)

## Quick Reference

### Jobs You Can Run Locally

```bash
# Validate workflow syntax
act -j validate-workflows --container-architecture linux/amd64

# Run Flask unit tests
act -j test --container-architecture linux/amd64

# Build and test Docker image
act -j docker-build --container-architecture linux/amd64

# Run security scan
act -j security-scan --container-architecture linux/amd64
```

### Jobs Requiring PR Process

The following cannot be tested locally - create a pull request instead:

- **Infrastructure changes** → PR triggers `infra-plan.yml`, merge triggers `infra-apply.yml`
- **ECR image push** → Merge to main with version tag triggers `push-to-ecr`
- **Cluster verification** → PR triggers `flux-validate.yml` and `verify-cluster.yml`

---

**Last Updated**: 2025-12-24
