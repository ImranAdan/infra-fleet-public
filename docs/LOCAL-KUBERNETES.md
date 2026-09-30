# Local Kubernetes

Use the [deployment profile guide](DEPLOYMENT-PROFILES.md) for requirements,
startup, access, verification and teardown.

This profile runs the application, Flux, Kyverno, Flagger, Envoy Gateway,
Prometheus/Grafana, metrics-server and Calico on kind. The Compose stack remains
available for faster application-only development.

After startup, open the [application control plane](APPLICATION-CONTROL-PLANE.md):

```bash
./fleet access --profile local --service dashboard
```

The dashboard at <http://localhost:9000/> shows every included app and can run
several together from the same deployed revision. The selected app remains the
default and cannot be stopped there.

The **Local Kubernetes** workflow runs the complete acceptance suite for every
app contract on pull requests that change runtime paths, weekly against `main`
and on demand. It records the exact revision in the `local` GitHub Environment
and tears the hosted-runner cluster down. See
[GitHub Environments](GITHUB-ENVIRONMENTS.md) for the gate and the distinction
between this ephemeral deployment and persistent AWS staging.

References:

- [Flux local quick start](https://fluxcd.io/flux/get-started/)
- [Kustomize bases and overlays](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)
- [Calico on kind](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind)
- [Flagger Gateway API integration](https://docs.flagger.app/tutorials/gatewayapi-progressive-delivery)
- [Envoy Gateway quick start](https://gateway.envoyproxy.io/docs/tasks/quickstart/)
