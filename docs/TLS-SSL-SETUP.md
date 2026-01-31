# TLS/SSL Setup with Cloudflare DNS and cert-manager

This document explains how automatic HTTPS is implemented for the infra-fleet platform using Cloudflare for DNS management and cert-manager for Let's Encrypt certificate management.

## Overview

The platform uses an ephemeral infrastructure model where the stack can be destroyed and rebuilt at any time. This requires automated DNS updates when the NLB IP changes.

**Our solution:**
- **Cloudflare DNS** - Automated DNS management via API
- **cert-manager** - Automates Let's Encrypt certificate issuance
- **NGINX Ingress** - Handles TLS termination

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL (HTTPS ONLY)                          │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   User Browser                                                           │
│        │                                                                 │
│        │ HTTPS (TLS 1.3)                                                │
│        ▼                                                                 │
│   ┌─────────────────────┐                                               │
│   │    Cloudflare DNS   │  app.example.com → NLB hostname            │
│   │    (DNS only mode)  │  Proxying OFF (grey cloud)                    │
│   └──────────┬──────────┘                                               │
│              │                                                           │
│              │ HTTPS (TLS 1.3)                                          │
│              ▼                                                           │
│   ┌─────────────────────┐                                               │
│   │   AWS NLB (L4 TCP)  │  Passthrough - no TLS termination            │
│   │   TCP:443 → 443     │                                               │
│   └──────────┬──────────┘                                               │
│              │                                                           │
└──────────────┼───────────────────────────────────────────────────────────┘
               │
┌──────────────┼───────────────────────────────────────────────────────────┐
│              │              KUBERNETES CLUSTER                           │
├──────────────┼───────────────────────────────────────────────────────────┤
│              │ HTTPS (TLS 1.3)                                          │
│              ▼                                                           │
│   ┌─────────────────────┐                                               │
│   │   NGINX Ingress     │  TLS termination                              │
│   │   Controller        │  Certificate from cert-manager                │
│   │                     │  (Let's Encrypt)                              │
│   └──────────┬──────────┘                                               │
│              │                                                           │
│              │ HTTP (internal only)                                     │
│              ▼                                                           │
│   ┌─────────────────────┐                                               │
│   │   load-harness Pod  │  Application                                  │
│   └─────────────────────┘                                               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## How It Works

### Certificate Lifecycle

```text
1. Stack rebuilds
   └── NLB provisioned with hostname

2. Workflow updates Cloudflare DNS
   └── app.example.com CNAME → NLB hostname

3. cert-manager detects ingress with TLS annotation
   └── Requests certificate from Let's Encrypt

4. Let's Encrypt performs HTTP-01 challenge
   └── Calls http://app.example.com/.well-known/acme-challenge/xxx
   └── cert-manager responds via NGINX ingress

5. Certificate issued and stored
   └── Secret: load-harness-tls

6. NGINX uses certificate
   └── HTTPS ready at https://app.example.com
```

### Why Cloudflare DNS-Only Mode?

We use Cloudflare in DNS-only mode (grey cloud, proxied=false) because:

1. **Flagger compatibility** - Traffic must flow directly to our NLB for NGINX-based canary routing
2. **End-to-end TLS** - We control the entire TLS chain with our own certificates
3. **No rate limits** - Using our own domain means our own Let's Encrypt quota (50 certs/week)

## Component Locations

| Component | Path | Purpose |
|-----------|------|---------|
| Cloudflare Provider | `infrastructure/staging/cloudflare.tf` | Terraform provider config |
| cert-manager HelmRelease | `k8s/infrastructure/cert-manager/helmrelease.yaml` | Deploys cert-manager |
| ClusterIssuer | `k8s/cert-manager-issuer/clusterissuer.yaml` | Let's Encrypt configuration |
| Ingress with TLS | `k8s/applications/load-harness/ingress-nginx.yaml` | TLS + hostname |
| Workflow DNS Step | `.github/workflows/rebuild-stack.yml` | Updates Cloudflare DNS |

## Configuration Details

### Ingress with TLS

```yaml
# k8s/applications/load-harness/ingress-nginx.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: load-harness
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - app.example.com
      secretName: load-harness-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: load-harness
                port:
                  number: 5000
```

### ClusterIssuer

```yaml
# k8s/cert-manager-issuer/clusterissuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            ingressClassName: nginx
```

### Workflow DNS Update

```yaml
# .github/workflows/rebuild-stack.yml
- name: Update Cloudflare DNS to point to NLB
  env:
    CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
    CLOUDFLARE_ZONE_ID: ${{ secrets.CLOUDFLARE_ZONE_ID }}
  run: |
    # Get NLB hostname
    NLB_HOST=$(kubectl get svc -n ingress-nginx ...)

    # Update Cloudflare DNS record
    curl -X PUT "https://api.cloudflare.com/client/v4/zones/$CLOUDFLARE_ZONE_ID/dns_records/$RECORD_ID" \
      -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      --data '{"type":"CNAME","name":"app","content":"'$NLB_HOST'","proxied":false}'
```

## Required Secrets

| Secret | Location | Purpose |
|--------|----------|---------|
| `CLOUDFLARE_API_TOKEN` | GitHub Secrets | DNS record management |
| `CLOUDFLARE_ZONE_ID` | GitHub Secrets | Zone identifier |
| `cloudflare_api_token` | Terraform Cloud | Provider authentication |
| `cloudflare_zone_id` | Terraform Cloud | Zone identifier |

## Verification Commands

```bash
# Check DNS resolution
dig app.example.com

# Check certificate status
kubectl get certificate -n applications

# Check certificate details
kubectl describe certificate load-harness-tls -n applications

# Check ClusterIssuer
kubectl get clusterissuer letsencrypt-prod

# Check ingress
kubectl get ingress -n applications

# Test HTTPS
curl -v https://app.example.com/health

# Test HTTP redirect
curl -I http://app.example.com/health
# Should return: 308 Permanent Redirect

# Check cert details
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```

## Troubleshooting

### Certificate not issuing

1. Check cert-manager is running:
   ```bash
   kubectl get pods -n cert-manager
   ```

2. Check certificate status:
   ```bash
   kubectl describe certificate load-harness-tls -n applications
   ```

3. Check ACME challenges:
   ```bash
   kubectl get challenges -A
   ```

4. Check cert-manager logs:
   ```bash
   kubectl logs -n cert-manager deploy/cert-manager
   ```

### DNS not resolving

1. Check Cloudflare dashboard for the DNS record
2. Verify the record is set to "DNS only" (grey cloud)
3. Wait for TTL to expire (300 seconds)

### HTTP-01 challenge failing

1. Ensure the NLB is accessible from the internet
2. Check NGINX ingress logs:
   ```bash
   kubectl logs -n ingress-nginx deploy/nginx-ingress-controller-ingress-nginx-controller
   ```

## Security Considerations

### What's Protected

- **In transit:** All external traffic encrypted with TLS 1.2/1.3
- **Certificate:** Valid Let's Encrypt certificate (browser trusted)
- **HSTS:** Strict-Transport-Security header enabled
- **Redirect:** HTTP automatically redirects to HTTPS

### Rate Limits

With our own domain (example.com), we have our own Let's Encrypt quota:

| Limit | Value | Impact |
|-------|-------|--------|
| Certificates per domain | 50/week | Plenty for rebuilds |
| Duplicate certificates | 5/week | Cached if same hostname |
| Failed validations | 5/hour | Retry after 1 hour |

## Related Documentation

- [SECURITY-CONCERNS.md](SECURITY-CONCERNS.md) - Security audit findings
- [PROGRESSIVE-DELIVERY.md](PROGRESSIVE-DELIVERY.md) - Canary deployments with Flagger
- [SELF-HOSTED-RUNNER.md](SELF-HOSTED-RUNNER.md) - GitHub Actions runner setup

## References

- [Cloudflare API](https://developers.cloudflare.com/api/)
- [cert-manager Documentation](https://cert-manager.io/docs/)
- [Let's Encrypt](https://letsencrypt.org/)
- [NGINX Ingress TLS](https://kubernetes.github.io/ingress-nginx/user-guide/tls/)
