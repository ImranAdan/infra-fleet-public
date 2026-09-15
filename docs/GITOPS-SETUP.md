# Flux GitOps setup

[Documentation index](README.md) · [Deployment profiles](DEPLOYMENT-PROFILES.md)

Flux reconciles an explicit cluster root under `k8s/clusters/`. The `./fleet`
facade selects that root and prepares its runtime inputs; shared application
resources never decide which provider to use.

## Bootstrap paths

The local profile creates a kind cluster, a workspace-owned registry and a
read-only Git HTTP source, then installs the slim Flux controller set. Run it
through the facade:

```bash
./fleet up --profile local
./fleet status --profile local
```

AWS bootstrapping remains in `.github/workflows/rebuild-stack.yml`. Terraform
creates a healthy EKS cluster before the workflow installs Flux. Terraform does
not use Kubernetes or Flux providers, so the destroy path still works when the
Kubernetes API is absent. Follow [configuration](../CONFIGURATION.md); do not
run `flux bootstrap` manually against this public template.

## Repository layout

```text
k8s/
├── applications/                  # shared workload and delivery contract
├── infrastructure/                # shared controllers and observability
├── profiles/
│   ├── local/                     # Envoy, local metrics and registry policy
│   └── aws-staging/               # AWS adapter, NGINX and ECR policy
├── clusters/
│   ├── local/                     # local Flux dependency graph
│   └── aws-staging/               # AWS Flux dependency graph
└── flux-system/
    ├── kustomization.yaml         # existing AWS bootstrap entry point
    └── flux-system/               # generated Flux components and sync source
```

`flux bootstrap github --path=k8s/flux-system` may regenerate the `gotk-*`
files. Profile and cluster resources live outside that generated directory.

The local dependency graph is:

```text
infrastructure -> routing -> policies -> applications
```

The AWS graph adapts the existing workflow output before consumers start:

```text
configuration -> infrastructure -> policies/certificate issuer -> applications
```

## Runtime configuration

Every reconciled layer reads a `flux-system/fleet-config` ConfigMap. The local
facade creates it from the owned registry, Gateway address, image commit and
generated credentials. The AWS configuration overlay translates the legacy
`terraform-outputs` ConfigMap into the same contract:

```text
terraform-outputs.ECR_REGISTRY -> fleet-config.IMAGE_REGISTRY
```

Other AWS values include `VPC_ID`, `CLUSTER_NAME`, `APP_HOSTNAME`,
`ACME_EMAIL` and `AWS_REGION`. Public CI substitutes fixed fixtures and fails
if a known placeholder remains unresolved. Runtime Secrets are created before
application reconciliation.

## Image automation

The AWS image reflector reads versioned tags from ECR through EKS Pod Identity.
Its policy selects semantic versions and image automation updates only
`k8s/profiles/aws-staging/applications/kustomization.yaml`. The shared
Deployment stays provider-independent. Releases and rebuilds test and scan an
image before publishing it.

The local profile builds the selected full Git revision, publishes a
commit-specific tag to its loopback registry and updates `fleet-config`.
`./fleet sync --profile local` republishes the read-only source snapshot and
reconciles every layer in dependency order.

## Verify reconciliation

The facade provides the normal operator view:

```bash
./fleet status --profile local
./fleet test --profile local
```

For a lower-level check against the selected kubeconfig:

```bash
flux check
flux get sources git -A
flux get kustomizations -A
flux get helmreleases -A
```

All selected Kustomizations and HelmReleases should report `Ready=True`.

## AWS routing limitation

AWS retains the retired community `ingress-nginx` controller while its Gateway
API replacement is designed. Its artifacts are pinned, but upstream no longer
provides security fixes. Keep this staging route private. The local profile
uses Envoy Gateway and does not certify the AWS ingress, IAM, DNS or TLS path.
