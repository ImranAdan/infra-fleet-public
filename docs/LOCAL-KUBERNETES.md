# Local Kubernetes

Use the [deployment profile guide](DEPLOYMENT-PROFILES.md) for requirements,
startup, access, verification and teardown.

This profile runs the application, Flux, Kyverno, Flagger, Envoy Gateway,
Prometheus/Grafana, metrics-server and Calico on kind. The Compose stack remains
available for faster application-only development.

For repository-wide integration evidence, dispatch the **Local Kubernetes**
workflow against the candidate branch. It records the exact revision in the
`local` GitHub Environment, executes the complete profile acceptance suite and
tears the hosted-runner cluster down. It runs on demand and weekly against
`main`; it does not run twice around every merge. See
[GitHub Environments](GITHUB-ENVIRONMENTS.md) for the gate and the distinction
between this ephemeral deployment and persistent AWS staging.

References:

- [Flux local quick start](https://fluxcd.io/flux/get-started/)
- [Kustomize bases and overlays](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)
- [Calico on kind](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind)
- [Flagger Gateway API integration](https://docs.flagger.app/tutorials/gatewayapi-progressive-delivery)
- [Envoy Gateway quick start](https://gateway.envoyproxy.io/docs/tasks/quickstart/)
