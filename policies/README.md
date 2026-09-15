# Kyverno policies

The selected deployment profile applies these CEL-based `ValidatingPolicy`
resources in CI and at admission time. Kyverno 1.19 evaluates the same policy
API in both places.

## Policy set

| Policy | Scope | Contract |
|---|---|---|
| `block-default-namespace` | Workload resources | A purpose-specific namespace is required |
| `block-latest-tag` | Pods and generated controllers | Every application, init and ephemeral container uses a version tag or digest |
| `require-rollout-capacity` | Application Deployments | Rolling updates keep all existing capacity, add integer surge capacity and probe every container |
| `require-local-images` | Local application pods and controllers | Every image comes from the profile-owned registry |
| `require-ecr-images` | AWS application pods and controllers | Every image comes from ECR |

Common policies live in this directory. Provider-specific registry policies
are composed by `k8s/profiles/<profile>/policies`; profiles must not apply both
registry policies.

Kyverno pod-controller autogeneration validates a controller before it creates
pods. The original Pod policy still checks the final object at admission time,
including init and ephemeral containers. Infrastructure Helm charts are
checked when their generated Pods reach the admission controller; public CI
does not download and expand those external charts.

## Change a policy

Use `apiVersion: policies.kyverno.io/v1`, `kind: ValidatingPolicy` and CEL
expressions. Keep `validationActions: [Deny]` for blocking controls. Add a
regression case under `tests/policies/` that demonstrates both an accepted and
a rejected resource, including a multi-container case for image rules.

Run all policy tests with the same Kyverno CLI version pinned in CI:

```bash
kyverno test tests/policies
```

Validate the full, substituted profile rather than an unresolved base:

```bash
kubectl kustomize k8s/profiles/local/policies > /tmp/local-policies.yaml
./scripts/render-profile.sh local > /tmp/local-resources.yaml
kyverno apply /tmp/local-policies.yaml \
  --resource /tmp/local-resources.yaml --table
```

The `k8s-manifest-validate` workflow performs this check for `local` and
`aws-staging`. Read [Deployment profiles](../docs/DEPLOYMENT-PROFILES.md) for
the composition boundary and [Rollout capacity](../docs/ROLLOUT-CAPACITY.md)
before changing the availability contract.

References: [ValidatingPolicy](https://kyverno.io/docs/policy-types/validating-policy/),
[CEL libraries](https://kyverno.io/docs/policy-types/cel-libraries/), and
[Kyverno CLI tests](https://kyverno.io/docs/subprojects/kyverno-cli/).
