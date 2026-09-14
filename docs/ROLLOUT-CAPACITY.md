# Application rollout capacity

Fleet issue [#44](https://github.com/ImranAdan/infra-fleet-public/issues/44)
was created from approved advisor report
[#47](https://github.com/ImranAdan/infra-fleet-advisor-public/pull/47).
Reviewing its controller evidence also exposed an application rollout gap.

## Application contract

Deployments in the `applications` namespace declare `RollingUpdate`, integer
`maxUnavailable: 0`, positive integer `maxSurge` and a readiness probe for every
container. Load Harness uses one surge pod. Its HPA ranges from one to eight
replicas; the previous default 25% unavailable budget allowed two unavailable
pods at eight replicas. Explicit zero unavailable capacity holds across that
range. See the [Kubernetes rollout specification](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment).

Surge capacity needs cluster headroom. When that capacity is unavailable, an
update waits rather than deliberately removing healthy old pods. This desired
state does not establish that a live deployment stays healthy under faults,
node loss or an invalid application readiness check.

The [Kyverno policy](../policies/require-rollout-capacity.yaml) checks these
application declarations in PR and main CI. Its regression cases exercise
single and scaled Deployments, default or nonzero unavailability, zero surge,
missing container readiness and the controller boundary. The policy is a CI
check; adding it here does not install an admission controller in a cluster.

## Generated controller boundary

The reported `flux-system/source-controller` comes from Flux's generated
component manifests. The pinned
[upstream source-controller v1.7.3 definition](https://github.com/fluxcd/source-controller/blob/v1.7.3/config/manager/deployment.yaml)
declares one replica, `Recreate`, a local artifact volume and a readiness probe.
[Flux documents](https://fluxcd.io/flux/installation/configuration/vertical-scaling/#persistent-storage-for-flux-internal-artifacts)
that its default artifact cache is ephemeral and must be restored after restart.

The application CI policy covers the `applications` namespace. Generated Flux
controllers retain upstream rollout semantics; the source-controller update
can temporarily interrupt artifact delivery. Plan controller maintenance and
verify reconciliation afterward. Any alternative controller strategy requires
a separately reviewed artifact-storage and availability design.

This exception does not make the controller's zero-capacity interval disappear.
The advisor's broader R-001 still reports it until an owner-approved intent
change narrows that rule. Issue closure records the reviewed disposition and
application fix, not proof of uninterrupted controller rollout. The publisher
preserves closed issue state on later runs.
