# Versioning Strategy

This repository contains both application and infrastructure code. We apply Semantic Versioning only to the application and document infra changes without assigning versions.

## Application Versioning (load-harness)

- Scope: `applications/load-harness`
- Version format: `vMAJOR.MINOR.PATCH` (e.g., `v1.0.0`)
- Release automation: release-please
- Release signals: Conventional Commit messages
- Image tags: Docker images published with the SemVer tag

## Infrastructure Changes

- Scope: `infrastructure/` and `k8s/`
- Versioning: no SemVer
- Tracking: document changes in PRs and in the changelog if relevant

## Release Flow (Application)

### 1. Development Phase
- Create feature branch from `main`
- Make changes following conventional commit format
- Open PR to `main`

**CI checks on PR:**
- ✅ Commit Message Lint - validates conventional commit format
- ✅ GitOps Validation - validates Flux manifests (if gitops files changed)
- ✅ Load Harness CI - builds/tests application (if app files changed)

### 2. Merge to Main
- Merge PR (squash merge recommended)
- GitHub creates merge commit on `main`

**CI checks on push to main:**
- ✅ Commit Message Lint - validates commits (skips Flux bots & merge commits)
- ✅ Release Please - analyzes commits, creates/updates release PR
- ✅ GitOps Validation - validates manifests (if gitops files changed)

### 3. Release Please Automation
- Runs on every push to `main`
- Analyzes all commits since last release
- Determines version bump based on conventional commits:
  - `feat:` → minor version (1.0.0 → 1.1.0)
  - `fix:` → patch version (1.0.0 → 1.0.1)
  - `feat!:` or `BREAKING CHANGE:` → major version (1.0.0 → 2.0.0)
- Creates or updates release PR with:
  - Version bump in manifest
  - Updated CHANGELOG.md
  - Release notes

### 4. Release Deployment
1. **Merge release PR** → creates git tag (e.g., `v1.0.0`)
2. **CI triggered by tag** → builds and pushes Docker image with SemVer tag
3. **Flux detects new image** → ImagePolicy selects latest SemVer tag
4. **Flux updates deployment** → commits new image tag to `k8s/` on main
5. **Kubernetes rolls out** → new version deployed to cluster

## CI/CD Architecture

### Workflows That Run on Main

| Workflow | Trigger | Purpose | Skips |
|----------|---------|---------|-------|
| **Commit Message Lint** | Every push | Validate conventional commits | Flux bots, GitHub merges |
| **Release Please** | Every push | Manage releases | N/A (always runs) |
| **GitOps Validation** | `k8s/**` changes | Validate manifests | Other file changes |
| **Load Harness CI** | `applications/load-harness/**` changes | Build/test/push images | Other file changes |

### Automated Commits (Skipped by Gitlint)

The following automated commits are excluded from commit message validation:

1. **Flux Image Automation** (`fluxcdbot@users.noreply.github.com`)
   - Updates deployment manifests with new image tags
   - Format: `chore: Update load-harness image`
   - Commits directly to `main` when new images detected

2. **GitHub Merge Commits** (`committer: noreply@github.com`)
   - Created when PRs are merged via GitHub UI
   - Uses PR title as commit message
   - May not follow strict conventional commit format

3. **Flux System Commits** (author: `Flux <empty-email>`)
   - Bootstrap and sync operations
   - Format: `Add Flux sync manifests`, `Init Flux with kustomize override`

## Configuration Details

### ImagePolicy SemVer Range
**File:** `k8s/infrastructure/flux-image-automation/image-policy.yaml`

```yaml
semver:
  range: '>=1.0.0'  # Accepts v1.0.0 and all future versions
```

⚠️ **Important:** Ensure the range matches your target release version. For example:
- For v1.x.x releases: `range: '>=1.0.0'`
- For v2.x.x releases: Update to `range: '>=2.0.0'`

### Release Please Configuration
**Files:** `release-please-config.json`, `.release-please-manifest.json`

The manifest tracks the current version. Release Please uses this as the baseline for determining the next version.

## Common Issues & Fixes

### Issue: ImagePolicy Won't Accept New Release
**Symptom:** Flux ignores newly released image tag
**Cause:** SemVer range in ImagePolicy excludes the version
**Fix:** Update `image-policy.yaml` semver range to include target version

### Issue: Deployment References Non-Existent Image
**Symptom:** Pods fail to pull image after merge
**Cause:** Deployment points to version tag that hasn't been built yet
**Fix:** Use `latest` tag until first release is created, then let Flux update

### Issue: Gitlint Fails on Main After Merge
**Symptom:** Commit Message Lint fails after PR merge
**Cause:** Merge commit or Flux commit doesn't follow conventional format
**Fix:** Already handled - workflow skips automated commits

### Issue: APP_VERSION Mismatch
**Symptom:** UI shows wrong version number
**Current:** Set as environment variable in deployment.yaml
**Future:** Should be baked into Docker image at build time using git tag

## Best Practices

1. **Always use conventional commits** - Required for automatic versioning
2. **Review release PRs carefully** - Verify version bump and changelog
3. **Don't manually edit version files** - Let release-please manage versions
4. **Monitor Flux after release** - Verify image update and deployment
5. **Keep ImagePolicy range updated** - Ensure new releases are accepted

## Testing a Release

Before merging a release PR:
1. Verify the version bump is correct (check release PR)
2. Review the generated changelog
3. Ensure ImagePolicy range includes the new version
4. Confirm CI will build the tag (check workflow triggers)
5. Merge and monitor: git tag → CI build → ECR push → Flux update → K8s rollout
