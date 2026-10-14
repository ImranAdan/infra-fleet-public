# Messaging

The platform runs one [NATS](https://nats.io) server with
[JetStream](https://docs.nats.io/nats-concepts/jetstream) in the `messaging`
namespace, in both profiles. Applications reach it at:

```
nats://nats.messaging.svc:4222
```

Applications declare their own streams, consumers and key-value buckets at
runtime, so the platform names no application and needs no change when an
app adds a channel.

## What the platform provides

| Concern | How |
|---|---|
| Broker | `nats` Helm chart 2.15.1 (`k8s/infrastructure/messaging/nats.yaml`), server image pinned by digest |
| Durability | JetStream file storage (256 MiB) on an `emptyDir`: streams survive a container restart, not a pod reschedule, the same ephemeral stance as Prometheus here |
| Isolation | NetworkPolicy admits only the `applications` namespace on 4222, and `observability` on the exporter port 7777 |
| Hardening | non-root (UID 1000), read-only root filesystem, all capabilities dropped, `RuntimeDefault` seccomp, no service account token |
| Metrics | `prometheus-nats-exporter` sidecar with a PodMonitor |
| Freshness | the monthly Chart Freshness check (`docs/DEPENDABOT.md`) covers the chart |

One server, no clustering: this is a lab platform, and a three-node JetStream
cluster would triple the broker's footprint on a single local node. A
reschedule loses messages in flight; apps should treat the broker as
at-least-once within a pod's lifetime and stay idempotent.

## Integration patterns

load-harness demonstrates five Enterprise Integration Patterns on this broker
(`applications/load-harness/README.md`, "Integration Pattern Endpoints"):

- **Work queue + Dead Letter Channel:** a work-queue stream with competing
  consumers; a poison message moves to `eip.dlq` after 3 deliveries.
- **Publish-Subscribe Channel:** independent durable subscribers each get every
  event.
- **Idempotent Receiver:** the broker's `Nats-Msg-Id` duplicate window, plus a
  ledger that records the id and applies the effect in one compare-and-set.
- **Content-Based Router:** orders routed by their `priority` field.
- **Splitter / Aggregator:** split by correlation id, aggregate with KV
  compare-and-set, and publish one result.

All of their state lives in the broker, because the HPA runs several pods and
any of them may consume a message. Every forwarding step publishes with a
message id taken from the message it consumed, so a redelivery cannot forward
twice.

## Using it from another application

Set `NATS_URL=nats://nats.messaging.svc:4222` in the app's Deployment. Egress
from `applications` is already open (`k8s/applications/platform/networkpolicy.yaml`).
Use any NATS client with JetStream, and keep subject and stream names prefixed
by the app, so two contracted apps never share a stream by accident.

## Verify it

```bash
kubectl get pods -n messaging
kubectl exec -n flux-system deploy/flagger-loadtester -- \
  hey -n 1 -m POST -T application/json -d '{"count":5,"poison":2}' \
  http://load-harness.applications:5000/api/eip/work   # add the API key header
```

`GET /api/eip/status` on load-harness then reports `dead_letter.messages: 2`
from the broker's own stream state.
