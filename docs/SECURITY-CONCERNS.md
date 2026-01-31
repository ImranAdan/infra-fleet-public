# Security Concerns and Hardening

This document tracks security findings, implemented mitigations, and outstanding concerns for the infra-fleet platform.

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

**Status:** Deferred - requires cert-manager setup and domain configuration.

**Options:**
- Deploy cert-manager with Let's Encrypt
- Use AWS ACM with ALB (loses Flagger traffic splitting)
- Use sslip.io for ephemeral environments

---

### C4: Workflow Approval Gates (Critical)

**Finding:** No approval gates on destructive workflows (nightly-destroy).

**Status:** Accepted risk - stack is ephemeral and can be rebuilt via `rebuild-stack.yml`.

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
| M8 | Grafana password in plan | Backlog |

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
