# Commit Messages

We use Conventional Commits to drive automated releases and changelogs.

Format:
```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types:
- feat: new feature (minor)
- fix: bug fix (patch)
- feat!: breaking change (major)
- docs, style, refactor, test, chore, ci, perf, revert: no version bump

Examples:
```
feat(api): add user authentication endpoint
fix(ui): resolve button alignment on mobile
feat!: redesign API response format

BREAKING CHANGE: API responses now use camelCase instead of snake_case
```

Local setup (optional but recommended):
```
pip install -r requirements-dev.txt
./scripts/install-git-hooks.sh
```

CI enforcement:
- The `Commit Message Lint` workflow runs `gitlint` on every PR and push to `main`/`develop`.
