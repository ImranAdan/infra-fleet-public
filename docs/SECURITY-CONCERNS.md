# Security Concerns and Hardening

This document tracks security findings, implemented mitigations, and outstanding concerns for the infra-fleet platform.

> This is a point-in-time audit trail, not setup guidance. Findings below keep
> their original wording for provenance, with current dispositions added where
> later changes superseded them. Use [SECURITY.md](../SECURITY.md) and
> [CONFIGURATION.md](../CONFIGURATION.md) for the supported deployment boundary.

## Static Code Security Audit

Completed: December 2025

### Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| Critical | 4 | 2 | 2 |
| High | 6 | 4 | 2 |
| Medium | 8 | 4 | 4 |
| Low | 6 | 0 | 6 |

---

## Implemented Mitigations

### C1: Pod Security Context (Critical)

**Finding:** Containers could run as root, allowing privilege escalation.

**Fix:** Added security context to deployment.

```yaml
# k8s/applications/load-harness/deployment.yaml
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
      - name: load-harness
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
              - ALL
```

**Defense in Depth:** Dockerfile also creates non-root user (UID 1000).

---

### C2: Network Policies (Critical)

**Finding:** No network isolation - all pods could communicate freely.

**Fix:** Created NetworkPolicy restricting ingress to NGINX and Prometheus only.

```yaml
# k8s/applications/load-harness/networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: load-harness
  namespace: applications
spec:
  podSelector:
    matchLabels:
      app: load-harness
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 5000
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: observability
      ports:
        - protocol: TCP
          port: 5000
  egress:
    - {}  # Permissive egress for now
```

---

### H1: Security Headers (High)

**Finding:** Missing HTTP security headers (CSP, HSTS, X-Frame-Options).

**Fix:** Added security headers middleware.

```python
# applications/load-harness/src/load_harness/middleware/security_headers.py
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
```

**Verification:**
```bash
curl -sI http://<endpoint>/ | grep -E "^X-"
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# X-XSS-Protection: 1; mode=block
```

---

### H4: Resource Quotas (High)

**Finding:** No resource limits on applications namespace - potential for resource exhaustion.

**Fix:** Added ResourceQuota.

```yaml
# k8s/infrastructure/namespaces/applications.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: applications-quota
  namespace: applications
spec:
  hard:
    requests.cpu: "4"
    limits.cpu: "8"
    requests.memory: 8Gi
    limits.memory: 16Gi
    pods: "20"
```

---

### H6: Flux Installation (High)

**Finding:** Flux installed via unverified `curl | bash` pattern.

**Fix:** Use official GitHub Action with verified checksums.

```yaml
# .github/actions/cleanup-kubernetes-resources/action.yml
- name: Install Flux CLI
  uses: fluxcd/flux2/action@main
```

---

### M1: Timing-Safe Comparison (Medium)

**Finding:** API key comparison vulnerable to timing attacks.

**Fix:** Use `hmac.compare_digest()` for constant-time comparison.

```python
# applications/load-harness/src/load_harness/middleware/auth.py
import hmac

if provided_key and hmac.compare_digest(provided_key, api_key):
    return None
```

---

### M6: Docker Build Security (Medium)

**Finding:** No .dockerignore - sensitive files could leak into image.

**Fix:** Created `.dockerignore` file.

```
# applications/load-harness/.dockerignore
.git
.env
.env.*
*.pyc
__pycache__
.pytest_cache
tests/
docs/
*.md
.coverage
htmlcov/
```

---

### M7: Secret Handling in Scripts (Medium)

**Finding:** API key echoed to terminal in ops script.

**Fix:** Removed direct secret echo, provide copy-friendly commands instead.

```bash
# ops/get-load-harness-api-key.sh
# Now outputs usage commands without exposing the raw key
```

---

## Deferred Items (GitHub Issues)

### C3: TLS/HTTPS (Critical) - Issue #295

**Finding:** Traffic unencrypted between client and NLB.

**Current disposition:** Optional TLS is implemented with cert-manager and a
configured hostname. The remaining blocker is the retired ingress controller;
do not expose it as a new public deployment.

**Options:**
- Deploy cert-manager with Let's Encrypt
- Use AWS ACM with ALB (loses Flagger traffic splitting)
- Use sslip.io for ephemeral environments

---

### C4: Workflow Approval Gates (Critical)

**Finding:** No approval gates on destructive workflows (nightly-destroy).

**Current disposition:** Resolved. Cleanup and Terraform destroy use the
protected `staging` environment, and manual dispatch requires the exact target
confirmation `destroy staging`.

---

### H2: CSRF Protection (High)

**Finding:** No CSRF protection on forms.

**Status:** Skipped - API-first design, browser sessions are secondary.

---

### H3: Service Account Token Auto-Mount (High)

**Finding:** Pods have unnecessary access to Kubernetes API.

**Status:** Skipped - low risk for this application, not accessing K8s API.

---

### H5: IAM Permission Scoping (High) - Issue #296

**Finding:** Overly broad IAM wildcards (`eks:*`, `ec2:*`, `iam:*`).

**Status:** Deferred - requires careful scoping to avoid breaking CI/CD.

---

### M2-M5, M8: Various Medium Issues

| ID | Finding | Status |
|----|---------|--------|
| M2 | No rate limiting | Backlog |
| M3 | imagePullPolicy not Always | Backlog |
| M4 | API_KEY secret optional | By design (dev mode) |
| M5 | EKS public API | Accepted risk |
| M8 | Grafana password in plan | Resolved: runtime Secret outside Terraform |

---

## Security Audit — 2026-09-11

Full-repository audit of the template as published. Tooling: `gitleaks` over
the entire commit history, `trivy config` across Terraform and Kubernetes,
`trivy image` against a locally built application image, `actionlint`,
`shellcheck`, plus manual review of workflow triggers, IAM, RBAC and the
application middleware.

Scope is this repository only. A deployment built from it inherits these
properties but adds its own credentials and cloud configuration.

### Verified sound

Recorded because a negative result is worth as much as a finding when the
alternative would have been serious.

| Check | Result |
|-------|--------|
| Secrets in git history | `gitleaks` reports 6 hits across 40 commits. **All six are the literal `test-api-key-12345`** in `conftest.py` and `test_app.py`. No real credential has ever been committed |
| `pull_request_target` | **Absent.** The standard route to credential theft in a public repository is not present anywhere |
| `issue_comment` triggers | None |
| Script injection | Untrusted values (`workflow_run.*`, `head_commit.message`) are passed through `env:`, not interpolated into `run:`. The one direct interpolation is `pull_request.number`, an integer GitHub controls |
| `workflow_run` handling | `dora-metrics.yml` runs with secrets, but checks out the **default branch**, not pull request head. No "pwn request" |
| Container image | 0 HIGH/CRITICAL with `--ignore-unfixed`, matching what CI enforces |
| Application headers | CSP, HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` all set by `middleware/security_headers.py` |
| Flask session key | Falls back to `secrets.token_hex(32)`, never a hardcoded default, and is supplied from a Secret in Kubernetes |
| Network policy | Present for the application |
| Repository controls | Secret scanning and push protection **enabled**; default workflow permission is `read`; `main` is protected |

### Findings

**H1 — Application container had a writable root filesystem** (`AVD-KSV-0014`)

`readOnlyRootFilesystem` was unset, while `pushgateway.yaml` in the same
repository sets it. Fixed. Verified by running the image with
`--read-only`: `/health`, `/metrics`, `/ui/` and `POST /load/cpu` all return
200 once gunicorn has a writable state directory, so the fix adds `emptyDir`
mounts for `/tmp` and `/home/app/.gunicorn`. Without them gunicorn logs
`Read-only file system: '/home/app/.gunicorn'` and the control server fails.

**H2 — No seccomp profile** (`AVD-KSV-0104`). Fixed: `RuntimeDefault` at pod
level.

**M1 — Third-party actions were pinned to mutable tags (resolved)**

Ten of twelve are pinned by tag, two by commit. A tag can be moved to point at
new code, which then runs with whatever credentials the job holds. This is not
hypothetical here: `trivy-action@0.33.1` stopped resolving when upstream
re-tagged, taking CI down with no commit in this repository. That was an
outage; the same mechanism is available for a compromise.

`sha_pinning_required` is `false` at repository level.

Current disposition: all third-party action references are pinned by full
commit SHA with a version comment. `scripts/validate-template-contract.sh`
rejects newly introduced version-tag references.

**M2 — `iam:PassRole` without a condition** (`AVD-AWS-0342`)

Present in the current stack. A narrower proposal exists, but it has not been
validated through a complete AWS apply/destroy cycle and should not be treated
as approved merely because it is open. IAM scoping remains follow-up work.

**L1 — Dependabot security updates are repository state.** Version updates are
configured in `.github/dependabot.yml`, but alerts and security-update pull
requests are separate GitHub settings that every adopter must verify.

**L2 — Workflows lacked a top-level permission baseline (resolved).** Each
workflow now declares its baseline explicitly; jobs add only the capabilities
they require. The template contract rejects workflows that omit the baseline.

**L3 — No `.gitleaks.toml`.** An adopter running a secret scan gets six false
positives from the test fixtures with nothing recording that they are expected.

### Not this repository's to fix

`trivy config` reports 9 CRITICAL and 7 MEDIUM findings in
`k8s/flux-system/flux-system/gotk-components.yaml` — a ClusterRole that can
manage all resources and read secrets cluster-wide, and a binding to
`cluster-admin`.

That file is generated by `flux bootstrap` and carries `DO NOT EDIT`. The
permissions are what Flux requires to reconcile arbitrary manifests; narrowing
them would break the GitOps controller, and any edit is reverted by the next
upgrade. They are listed here so the count is not mistaken for something
actionable.

---
## Positive Security Findings

### Application Security
- Robust input validation on all endpoints
- No dangerous functions (eval, exec, os.system, pickle)
- Secure secret key generation (`secrets.token_hex(32)`)
- Session cookies: HttpOnly, SameSite=Lax
- Jinja2 auto-escaping prevents XSS
- Dependencies pinned to specific versions

### Infrastructure Security
- OIDC authentication for AWS (no static credentials)
- ECR images immutable with scan-on-push
- IMDSv2 enforced on EKS nodes (SSRF protection)
- Worker nodes in private subnets
- Trivy scans block vulnerable images

### CI/CD Security
- Secrets in GitHub Secrets (not hardcoded)
- Dependabot configured for all ecosystems
- Multi-stage Docker builds with non-root user
- Terraform state encrypted in Terraform Cloud

---

## Verification Commands

```bash
# Check pod security context
kubectl get pod -n applications -l app=load-harness \
  -o jsonpath='{.items[0].spec.securityContext}'

# Verify running as non-root
kubectl exec -n applications deploy/load-harness -- id

# Check NetworkPolicy
kubectl get networkpolicy -n applications

# Test security headers
curl -sI -H "X-API-Key: $API_KEY" http://<endpoint>/ | grep "^X-"

# Check ResourceQuota usage
kubectl get resourcequota -n applications
```

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
