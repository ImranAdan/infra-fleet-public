# GitHub Actions Self-Hosted Runner (Docker)

A containerized GitHub Actions self-hosted runner with all CI dependencies pre-installed.

## Quick Start

### 1. Get a GitHub Token

You need either:
- **Personal Access Token (PAT)** with `repo` scope - [Create one here](https://github.com/settings/tokens/new?scopes=repo)
- **Runner Registration Token** - Get from [Runner Settings](https://github.com/your-org/infra-fleet/settings/actions/runners/new)

### 2. Start the Runner

#### Option A: Using docker-compose (Recommended)

```bash
cd ops/runner

# Create .env file
cp .env.example .env
# Edit .env and add your GITHUB_TOKEN

# Start the runner
docker-compose up -d

# View logs
docker-compose logs -f
```

#### Option B: Direct docker run

```bash
# Build the image
docker build -t infra-fleet-runner ops/runner/

# Run the container
docker run -d \
  --name infra-fleet-runner \
  -e GITHUB_TOKEN=your-token-here \
  -v /var/run/docker.sock:/var/run/docker.sock \
  infra-fleet-runner
```

### 3. Verify Registration

Check the runner appears in GitHub: <https://github.com/your-org/infra-fleet/settings/actions/runners>

## Included Dependencies

The runner image includes all tools needed for the infra-fleet CI pipelines:

| Category | Tools |
|----------|-------|
| **Core** | git, curl, jq, unzip |
| **Python** | python3, pip, yamllint, gitlint, pytest |
| **Infrastructure** | terraform, kubectl, aws-cli, eksctl |
| **GitOps** | flux, helm |
| **Validation** | kubeconform, kyverno-cli, actionlint |
| **Security** | trivy |
| **Docker** | docker-cli (via socket mount) |
| **GitHub** | gh (GitHub CLI) |

## Configuration

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes | - | PAT or runner registration token |
| `RUNNER_NAME` | No | `docker-runner` | Name shown in GitHub |
| `RUNNER_LABELS` | No | `self-hosted,Linux,X64,docker` | Comma-separated labels |
| `GITHUB_REPOSITORY` | No | `your-org/infra-fleet` | Target repository |

## Updating Workflows to Use This Runner

Your workflows should use `runs-on: self-hosted`:

```yaml
jobs:
  build:
    runs-on: self-hosted  # Uses this Docker runner
    steps:
      - uses: actions/checkout@v4
      # ... rest of your job
```

## Docker-in-Docker

The runner mounts the host's Docker socket (`/var/run/docker.sock`) to enable:
- Building Docker images
- Running containers for testing
- Security scanning with Trivy

## Stopping the Runner

```bash
# Using docker-compose
docker-compose down

# Using docker directly
docker stop infra-fleet-runner
docker rm infra-fleet-runner
```

## Updating the Runner

```bash
# Rebuild with latest versions
docker-compose build --no-cache
docker-compose up -d
```

## Troubleshooting

### Runner not appearing in GitHub
- Check logs: `docker-compose logs`
- Verify token is valid and has correct permissions
- Ensure token hasn't expired (registration tokens expire in 1 hour)

### Docker commands failing
- Ensure Docker socket is mounted: `-v /var/run/docker.sock:/var/run/docker.sock`
- Check Docker daemon is running on host

### Permission denied errors
- The runner runs as non-root user `runner`
- Docker socket permissions may need adjustment on some systems
