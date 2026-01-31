# Self-Hosted GitHub Actions Runner

This document explains how to set up and use a self-hosted GitHub Actions runner for the infra-fleet repository, enabling unlimited CI/CD without GitHub Actions minute limits.

## Why Self-Hosted?

GitHub Actions charges for minutes on private repositories:

| Plan | Minutes/Month | Cost |
|------|---------------|------|
| Free | 2,000 | $0 |
| Pro | 3,000 | $4/mo |
| Team | 3,000 | $4/user/mo |

With frequent stack rebuilds and destroys, these limits are quickly exhausted. A self-hosted runner provides **unlimited minutes at no cost**.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         GITHUB                                  │
│                                                                 │
│  Push/PR ──▶ Workflow Triggered ──▶ "Need a runner"            │
│                                           │                     │
└───────────────────────────────────────────┼─────────────────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    │                       │                       │
                    ▼                       ▼                       ▼
         ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
         │  GitHub-Hosted   │    │  Your Mac        │    │  EC2 (future)    │
         │  ubuntu-latest   │    │  self-hosted     │    │  self-hosted     │
         │                  │    │                  │    │                  │
         │  Uses minutes ⚠️  │    │  FREE ✅         │    │  FREE ✅         │
         └──────────────────┘    └──────────────────┘    └──────────────────┘
```

The runner is a lightweight program that:
1. Connects to GitHub via HTTPS
2. Polls for jobs assigned to this repository
3. Executes workflow steps locally
4. Streams logs back to GitHub UI
5. Reports success/failure

## Setup (One-Time)

### Prerequisites

Ensure these tools are installed on your Mac:

```bash
# Required by workflows
brew install awscli terraform kubectl helm fluxcd/tap/flux

# Verify
aws --version
terraform --version
kubectl version --client
flux --version
```

### Install Runner

```bash
# Run the setup script
./ops/setup-runner.sh
```

The script will:
1. Download the GitHub Actions runner
2. Ask you for a registration token
3. Configure and register the runner

**To get the token:**
1. Go to https://github.com/your-org/infra-fleet/settings/actions/runners/new
2. Select **macOS** and your architecture (ARM64 for M1/M2/M3)
3. Copy the token from the `./config.sh` command shown

## Daily Usage

### Start Runner

```bash
# Foreground (see logs in terminal)
./ops/start-runner.sh

# Background (runs silently)
./ops/start-runner.sh --background
```

### Stop Runner

```bash
# If running in foreground
Ctrl+C

# If running in background
./ops/stop-runner.sh
```

### Check Status

In GitHub: **Settings → Actions → Runners**

```
┌────────────────────────────────────────────────────────────────┐
│  Self-hosted runners                                           │
├────────────────────────────────────────────────────────────────┤
│  🟢 local-mac-hostname    macOS    Idle       arm64            │
└────────────────────────────────────────────────────────────────┘
```

- 🟢 **Idle** - Runner is online, waiting for jobs
- 🟡 **Active** - Currently running a job
- ⚫ **Offline** - Runner is not running

## Workflows Using Self-Hosted

These workflows are configured to use `runs-on: self-hosted`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `release-please.yml` | Push to main | Version management |
| `rebuild-stack.yml` | Manual dispatch | Build infrastructure |
| `nightly-destroy.yml` | Schedule/Manual | Destroy infrastructure |
| `infra-apply.yml` | Push to main | Apply Terraform |
| `infra-plan.yml` | Pull requests | Plan Terraform |

Other workflows still use `ubuntu-latest` (GitHub-hosted).

## Workflow Configuration

To use self-hosted runner in a workflow:

```yaml
jobs:
  build:
    runs-on: self-hosted  # Instead of ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # ... rest of steps
```

## Troubleshooting

### Runner Not Picking Up Jobs

1. **Check runner is online:**
   ```bash
   pgrep -f "Runner.Listener" && echo "Running" || echo "Not running"
   ```

2. **Check GitHub UI:**
   https://github.com/your-org/infra-fleet/settings/actions/runners

3. **Restart runner:**
   ```bash
   ./ops/stop-runner.sh
   ./ops/start-runner.sh
   ```

### Job Fails with Tool Not Found

Install missing tools:
```bash
brew install <tool-name>
```

Common tools needed:
- `awscli` - AWS operations
- `terraform` - Infrastructure
- `kubectl` - Kubernetes
- `helm` - Helm charts
- `flux` - GitOps
- `jq` - JSON processing
- `yq` - YAML processing

### Runner Token Expired

Tokens expire after 1 hour. Get a new one:
1. Go to GitHub → Settings → Actions → Runners
2. Click "New self-hosted runner"
3. Copy the new token
4. Re-run setup:
   ```bash
   rm -rf ~/actions-runner
   ./ops/setup-runner.sh
   ```

### Workflow Queued But Not Running

If the runner is offline, jobs queue indefinitely. Either:
- Start the runner: `./ops/start-runner.sh`
- Or re-run the job when runner is online

## Security Considerations

### What the Runner Can Access

When running on your Mac, the runner has access to:
- Your AWS credentials (`~/.aws/`)
- Your kubeconfig (`~/.kube/config`)
- Your file system
- Network access

### Best Practices

1. **Only run on trusted repos** - The runner executes workflow code
2. **Don't run on public repos** - Anyone could submit a PR with malicious code
3. **Keep tools updated** - `brew upgrade`
4. **Review PRs before running** - Especially from forks

### Repository Security

This repo is **private**, so only collaborators can trigger workflows. This is safe for self-hosted runners.

## Alternative: EC2 Runner

For always-on CI without keeping your Mac running, consider an EC2-based runner:

```
infrastructure/permanent/
└── github-runner.tf   # Future: t3.micro with runner
```

See issue #303 for implementation tracking.

## Cost Comparison

| Approach | Monthly Cost | Always Available |
|----------|--------------|------------------|
| GitHub Pro | $4 | Yes (3000 mins) |
| Self-hosted Mac | $0 | When running |
| Self-hosted EC2 | ~$8 | Yes |

## Files Reference

| File | Purpose |
|------|---------|
| `ops/setup-runner.sh` | One-time runner installation |
| `ops/start-runner.sh` | Start runner (foreground/background) |
| `ops/stop-runner.sh` | Stop background runner |
| `~/actions-runner/` | Runner installation directory |
| `~/actions-runner/_work/` | Job working directory |

## Related Documentation

- [GitHub Self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners)
- [Runner releases](https://github.com/actions/runner/releases)
- Issue #303 - EC2 runner evaluation
