# Flux GitOps setup

Flux is bootstrapped by `.github/workflows/rebuild-stack.yml` after Terraform
has created a healthy cluster. Terraform does not use Kubernetes or Flux
providers, so it can also destroy the cluster when the Kubernetes API is gone.

Follow [../CONFIGURATION.md](../CONFIGURATION.md) for the supported initial
setup. Do not run `flux bootstrap` against this public template.

## Repository layout

```text
k8s/flux-system/
├── kustomization.yaml                 # root bootstrap entry point
├── platform-kustomizations.yaml       # infrastructure/issuer/app ordering
└── flux-system/
    ├── gotk-components.yaml           # generated Flux controllers
    ├── gotk-sync.yaml                 # generated repository source/sync
    └── kustomization.yaml             # generated-file aggregation
```

`flux bootstrap github --path=k8s/flux-system` may regenerate the two `gotk-*`
files. The custom platform Kustomizations live outside that generated
directory so bootstrap cannot silently discard them.

The platform reconciliation order is:

```text
infrastructure -> cert-manager-issuer -> applications
```

## Runtime substitution

The rebuild workflow creates `flux-system/terraform-outputs` before Flux is
bootstrapped. Each platform Kustomization uses `postBuild.substituteFrom` to
resolve deployment-specific values such as:

- `${ECR_REGISTRY}`;
- `${VPC_ID}` and `${CLUSTER_NAME}`;
- `${APP_HOSTNAME}`; and
- `${ACME_EMAIL}`.

The public CI renders deterministic fixture values before schema and Kyverno
validation. An unresolved known placeholder is a validation failure.

Runtime Secrets are also created before reconciliation. Applying `k8s/`
directly to an empty cluster is therefore not a supported bootstrap path.

## Image automation

The image-reflector controller reads versioned tags from the permanent ECR
repository through EKS Pod Identity. The ImagePolicy selects semantic versions
and image automation commits the chosen tag to the deployment manifest.
Release tags and the rebuild path test and scan an image before publishing it.

## Verify reconciliation

The rebuild workflow calls the reusable cluster and Flux verification
workflows. For an operator check:

```bash
flux check
flux get sources git -A
flux get kustomizations -A
flux get helmreleases -A
```

All Kustomizations and HelmReleases should report `Ready=True`.

## Known migration

The current progressive-delivery graph still depends on retired community
`ingress-nginx`. The Helm input is frozen so a rebuild cannot drift to a new
artifact, but upstream no longer supplies security fixes. A Gateway API
migration must replace its routing and Prometheus metric contract before this
path is suitable for public exposure.
