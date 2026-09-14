# TLS and optional DNS

The staging manifests contain a cert-manager `ClusterIssuer` and an
application TLS route. Deployment-specific values are injected by Flux from
the `terraform-outputs` ConfigMap; no real hostname or email address is
committed.

> The current route uses retired community `ingress-nginx`. Do not expose a
> new public deployment until the Gateway API migration has been implemented
> and live-cycle tested. See [../SECURITY.md](../SECURITY.md).

## Without a domain

Leave `APP_HOSTNAME` and `ACME_EMAIL` unset. The rebuild uses the reserved
`.invalid` domain, which cannot resolve publicly. Reach the application with:

```bash
kubectl port-forward -n applications svc/load-harness 8080:5000
```

This is the recommended way to inspect the current staging preview.

## With a Cloudflare-managed domain

Set these repository variables together:

```text
APP_HOSTNAME=app.your-domain.example
ACME_EMAIL=platform-owner@your-domain.example
```

For automated DNS, also set both `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ZONE_ID` as repository secrets. The token needs DNS edit access
only for the relevant zone. The rebuild workflow rejects partial domain or
Cloudflare configuration before creating infrastructure.

After Flux creates the ingress load balancer, the workflow creates or updates
an unproxied CNAME for the full `APP_HOSTNAME`. cert-manager then completes the
Let's Encrypt HTTP-01 challenge and stores the certificate in
`applications/load-harness-tls`.

You may manage the same CNAME outside Cloudflare; omit both Cloudflare secrets
in that case.

## Inspect status

```bash
kubectl get ingress -n applications load-harness
kubectl get certificate,certificaterequest,challenge -n applications
kubectl describe certificate -n applications load-harness-tls
```

The non-routable default is intentional. A certificate cannot become ready
until a real hostname resolves to the current load balancer.
