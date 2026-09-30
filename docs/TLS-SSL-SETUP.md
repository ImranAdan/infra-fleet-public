# TLS and optional DNS

Both profiles serve the app through one Envoy Gateway (`k8s/routing`): its
`http` listener only redirects to HTTPS, and its `https` listener terminates TLS
with the cert-manager certificate `envoy-gateway-system/fleet-tls` for
`APP_HOSTNAME`. Each profile supplies the `fleet-issuer` ClusterIssuer:
Let's Encrypt on AWS; locally, a CA whose self-signed root lives only in the
cluster (`k8s/profiles/local/routing/issuer.yaml`). Locally the certificate also
covers `*.apps.localhost` and the listener accepts any host, so every app
launched from the dashboard gets its own route host. Deployment-specific values are
injected by Flux from the `terraform-outputs` ConfigMap; no real hostname or
email address is committed.

> The AWS route is live-tested locally only. Do not expose a new public
> deployment until an AWS apply, certificate issue and teardown cycle has
> passed. See [../SECURITY.md](../SECURITY.md).

## Without a domain

Leave `APP_HOSTNAME` and `ACME_EMAIL` unset. The rebuild uses the reserved
`.invalid` domain, which cannot resolve publicly. Reach the application with:

```bash
kubectl port-forward -n applications svc/load-harness 8080:5000   # svc/<APP_NAME> for another app
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

After Flux creates the Gateway's load balancer (the `fleet-gateway` Service),
the workflow creates or updates an unproxied CNAME for the full `APP_HOSTNAME`.
cert-manager then completes the Let's Encrypt HTTP-01 challenge through a
temporary route on the Gateway's `http` listener and stores the certificate in
`envoy-gateway-system/fleet-tls`.

You may manage the same CNAME outside Cloudflare; omit both Cloudflare secrets
in that case.

## Inspect status

```bash
kubectl get gateway,httproute -A
kubectl get certificate,certificaterequest,challenge -n envoy-gateway-system
kubectl describe certificate -n envoy-gateway-system fleet-tls
```

The non-routable default is intentional. A certificate cannot become ready
until a real hostname resolves to the current load balancer.
