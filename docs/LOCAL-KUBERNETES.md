# Local Kubernetes

Use the [deployment profile guide](DEPLOYMENT-PROFILES.md) for requirements,
startup, access, verification and teardown.

This profile runs the application, Flux, Kyverno, Flagger, Envoy Gateway,
Prometheus/Grafana, metrics-server and Calico on kind. The Compose stack remains
available for faster application-only development.

References:

- [Flux local quick start](https://fluxcd.io/flux/get-started/)
- [Kustomize bases and overlays](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)
- [Calico on kind](https://docs.tigera.io/calico/latest/getting-started/kubernetes/kind)
- [Flagger Gateway API integration](https://docs.flagger.app/tutorials/gatewayapi-progressive-delivery)
- [Envoy Gateway quick start](https://gateway.envoyproxy.io/docs/tasks/quickstart/)
