"""Enterprise Integration Patterns on NATS JetStream.

Each pattern keeps its state in the broker, not in this process: the HPA runs
several pods, and any of them may consume a given message. Status is read back
from stream, consumer and key-value state, so it is the broker's account of
what happened.

- Work queue + Dead Letter Channel: EIP_WORK is a work-queue stream shared by
  competing consumers. A poison message is retried; on its last permitted
  delivery it is copied to eip.dlq and terminated.
- Publish-Subscribe Channel: every event on eip.events.> reaches each durable
  subscriber (audit and notify) independently.
- Idempotent Receiver: the broker drops a republished Nats-Msg-Id inside the
  duplicate window, and the ledger records the payment id and adds its amount
  in one compare-and-set, so a second message for the same payment is skipped
  and a failure part-way loses nothing.
- Content-Based Router: orders on eip.orders.in move to eip.orders.priority or
  eip.orders.standard by their priority field.
- Splitter / Aggregator: a batch on eip.batch.in is split into items, each item
  is processed, and the results are aggregated by correlation id in KV until
  the batch is complete.

Every forwarding step publishes with a message id taken from the message it
consumed, so a redelivery cannot forward the same message twice.
"""

import asyncio
import json
import logging
import re
import threading
import uuid

import nats
from nats.errors import TimeoutError as NatsTimeout
from nats.js.api import ConsumerConfig, RetentionPolicy, StreamConfig
from nats.js.errors import KeyWrongLastSequenceError, NotFoundError
from prometheus_client import Counter

log = logging.getLogger(__name__)

MAX_DELIVER = 3
ACK_WAIT_SECONDS = 2
# Forwarding steps publish with a message id from the source message, so a
# redelivery (after ACK_WAIT_SECONDS) is dropped by the broker. ponytail: an
# unacknowledged message redelivered after this window would forward twice;
# raise it if consumers can stall for longer.
DUPLICATE_WINDOW_SECONDS = 600
RETRY_SECONDS = 2
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

STREAMS = (
    StreamConfig(name="EIP_WORK", subjects=["eip.work"], retention=RetentionPolicy.WORK_QUEUE),
    StreamConfig(name="EIP_DLQ", subjects=["eip.dlq"], duplicate_window=DUPLICATE_WINDOW_SECONDS),
    StreamConfig(name="EIP_EVENTS", subjects=["eip.events.>"]),
    StreamConfig(name="EIP_ORDERS", subjects=["eip.orders.>"], duplicate_window=DUPLICATE_WINDOW_SECONDS),
    StreamConfig(name="EIP_BATCH", subjects=["eip.batch.>"], duplicate_window=DUPLICATE_WINDOW_SECONDS),
    StreamConfig(name="EIP_PAYMENTS", subjects=["eip.payments"], duplicate_window=DUPLICATE_WINDOW_SECONDS),
)
SUBSCRIBERS = ("audit", "notify")

MESSAGES = Counter(
    "eip_messages_total", "Messages handled by an integration pattern", ["pattern", "outcome"]
)


def _payload(msg):
    return json.loads(msg.data or b"{}")


def _from(msg, step):
    """A message id for what `step` publishes from msg: the same on redelivery."""
    return {"Nats-Msg-Id": f"{step}-{msg.metadata.stream}-{msg.metadata.sequence.stream}"}


def apply_payment(ledger, payment):
    """Record the payment and add its amount in one state change, or not at all.

    ponytail: `applied` grows by one id per payment; fine for a demo ledger,
    use a per-payment key with an expiring guard for unbounded volume.
    """
    if payment["payment_id"] in ledger["applied"]:
        return ledger
    return {"total": ledger["total"] + payment["amount"], "applied": [*ledger["applied"], payment["payment_id"]]}


class MessagingUnavailable(RuntimeError):
    """The broker is not reachable yet; the routes answer 503."""


class Messaging:
    """Owns one NATS connection on a private event loop thread."""

    def __init__(self, url):
        self.url = url
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.error = None
        threading.Thread(target=self._run, name="eip-loop", daemon=True).start()

    # Flask calls these from request threads. While the broker is unreachable
    # this fails within READY_WAIT, so requests never hold gunicorn's threads.
    READY_WAIT = 2

    def call(self, coroutine, timeout=10):
        if not self.ready.wait(self.READY_WAIT):
            coroutine.close()
            raise MessagingUnavailable(f"messaging not ready: {self.error or 'connecting'}")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def close(self):
        """Stop the consumers, close the connection and the loop."""
        if self.ready.is_set():
            self.call(self._shutdown())
        self.loop.call_soon_threadsafe(self.loop.stop)

    async def _shutdown(self):
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.nc.close()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._start())
        self.loop.run_forever()

    async def _start(self):
        """Connect and declare everything, retrying until the broker is there."""
        while True:
            try:
                self.nc = await nats.connect(self.url, name="load-harness", max_reconnect_attempts=-1)
                self.js = self.nc.jetstream()
                for config in STREAMS:
                    await self._ensure_stream(config)
                self.aggregates = await self.js.create_key_value(bucket="eip_aggregates")
                self.ledger = await self.js.create_key_value(bucket="eip_ledger")
                await self._start_consumers()
                break
            except Exception as error:  # surfaced by call(); the app keeps serving
                self.error = error
                log.warning("messaging not started (%s); retrying in %ss", error, RETRY_SECONDS)
                if getattr(self, "nc", None) is not None:
                    await self.nc.close()
                    self.nc = None
                await asyncio.sleep(RETRY_SECONDS)
        self.error = None
        self.ready.set()

    async def _ensure_stream(self, config):
        try:
            await self.js.stream_info(config.name)
            await self.js.update_stream(config)
        except NotFoundError:
            await self.js.add_stream(config)

    async def _start_consumers(self):
        await self._consume("eip.work", "workers", self._work, max_deliver=MAX_DELIVER)
        for name in SUBSCRIBERS:
            await self._consume("eip.events.>", name, self._subscriber(name))
        await self._consume("eip.payments", "ledger", self._ledger)
        await self._consume("eip.orders.in", "router", self._route)
        await self._consume("eip.batch.in", "splitter", self._split)
        await self._consume("eip.batch.item", "processor", self._process_item)
        await self._consume("eip.batch.done", "aggregator", self._aggregate)

    async def _consume(self, subject, durable, handler, max_deliver=-1):
        config = ConsumerConfig(ack_wait=ACK_WAIT_SECONDS, max_deliver=max_deliver)
        subscription = await self.js.pull_subscribe(subject, durable=durable, config=config)

        async def loop():
            while True:
                try:
                    batch = await subscription.fetch(10, timeout=1)
                except NatsTimeout:
                    continue
                except Exception:  # broker restart or reconnect: back off, keep consuming
                    log.exception("fetch failed on %s", durable)
                    await asyncio.sleep(1)
                    continue
                for msg in batch:
                    try:
                        await handler(msg)
                    except Exception:
                        log.exception("%s handler failed; message will be redelivered", durable)
                        await msg.nak()

        self.loop.create_task(loop())

    # Work queue + Dead Letter Channel
    async def _work(self, msg):
        job = _payload(msg)
        if not job.get("poison"):
            await msg.ack()
            MESSAGES.labels("work-queue", "processed").inc()
            return
        if msg.metadata.num_delivered < MAX_DELIVER:
            await msg.nak()
            MESSAGES.labels("work-queue", "retried").inc()
            return
        headers = {"Eip-Original-Subject": msg.subject, "Eip-Deliveries": str(MAX_DELIVER), **_from(msg, "dlq")}
        await self.js.publish("eip.dlq", msg.data, headers=headers)
        await msg.term()
        MESSAGES.labels("dead-letter", "dead-lettered").inc()

    # Publish-Subscribe Channel
    def _subscriber(self, name):
        async def handle(msg):
            await msg.ack()
            MESSAGES.labels("publish-subscribe", name).inc()

        return handle

    # Idempotent Receiver
    async def _ledger(self, msg):
        payment = _payload(msg)
        # The guard and the total change together, so a failure part-way leaves
        # neither, and the redelivery applies the payment.
        old, new = await self._cas(
            self.ledger, "ledger", lambda state: apply_payment(state, payment), lambda: {"total": 0, "applied": []}
        )
        await msg.ack()
        applied = old is None or payment["payment_id"] not in old["applied"]
        MESSAGES.labels("idempotent-receiver", "processed" if applied else "duplicate-skipped").inc()

    # Content-Based Router
    async def _route(self, msg):
        order = _payload(msg)
        lane = "priority" if order.get("priority") == "high" else "standard"
        await self.js.publish(f"eip.orders.{lane}", msg.data, headers=_from(msg, "route"))
        await msg.ack()
        MESSAGES.labels("content-based-router", lane).inc()

    # Splitter / Aggregator
    async def _split(self, msg):
        batch = _payload(msg)
        items = batch["items"]
        for index, value in enumerate(items):
            item = {"correlation_id": batch["correlation_id"], "index": index, "total": len(items), "value": value}
            headers = {"Nats-Msg-Id": f"{_from(msg, 'split')['Nats-Msg-Id']}-{index}"}
            await self.js.publish("eip.batch.item", json.dumps(item).encode(), headers=headers)
        await msg.ack()
        MESSAGES.labels("splitter", "split").inc()

    async def _process_item(self, msg):
        item = _payload(msg)
        item["result"] = item["value"] * item["value"]
        await self.js.publish("eip.batch.done", json.dumps(item).encode(), headers=_from(msg, "process"))
        await msg.ack()

    async def _aggregate(self, msg):
        item = _payload(msg)
        key = item["correlation_id"]

        def add_part(state):
            state["parts"][str(item["index"])] = item["result"]
            if len(state["parts"]) == state["total"]:
                state["result"] = sum(state["parts"].values())
            return state

        # Compare-and-set, so aggregators on several pods never lose a part.
        old, new = await self._cas(self.aggregates, key, add_part, lambda: {"total": item["total"], "parts": {}})
        if "result" in new and "result" not in (old or {}):
            # Publish on completion only; the message id makes a redelivery harmless.
            result = json.dumps({"correlation_id": key, "result": new["result"]}).encode()
            await self.js.publish(f"eip.batch.result.{key}", result, headers={"Nats-Msg-Id": f"result-{key}"})
            MESSAGES.labels("aggregator", "completed").inc()
        await msg.ack()

    async def _cas(self, kv, key, change, initial):
        """Apply change(state) to a KV entry with compare-and-set; return (old, new)."""
        while True:
            try:
                entry = await kv.get(key)
                old, revision = json.loads(entry.value), entry.revision
            except NotFoundError:
                old, revision = None, None
            new = change(json.loads(json.dumps(old)) if old is not None else initial())
            value = json.dumps(new).encode()
            try:
                if revision is None:
                    await kv.create(key, value)
                else:
                    await kv.update(key, value, last=revision)
                return old, new
            except KeyWrongLastSequenceError:
                continue

    # Producers, called through call()
    async def send_work(self, count, poison):
        for index in range(count):
            body = {"id": str(uuid.uuid4()), "poison": index < poison}
            await self.js.publish("eip.work", json.dumps(body).encode())

    async def publish_event(self, kind):
        await self.js.publish(f"eip.events.{kind}", json.dumps({"type": kind}).encode())

    async def send_payment(self, payment_id, amount, message_id):
        body = json.dumps({"payment_id": payment_id, "amount": amount}).encode()
        ack = await self.js.publish("eip.payments", body, headers={"Nats-Msg-Id": message_id})
        return bool(ack.duplicate)

    async def send_orders(self, orders):
        for order in orders:
            await self.js.publish("eip.orders.in", json.dumps(order).encode())

    async def send_batch(self, items):
        correlation_id = uuid.uuid4().hex
        body = {"correlation_id": correlation_id, "items": items}
        await self.js.publish("eip.batch.in", json.dumps(body).encode())
        return correlation_id

    async def batch_result(self, correlation_id):
        """The aggregate's state and the result message it published, if any."""
        try:
            state = json.loads((await self.aggregates.get(correlation_id)).value)
        except NotFoundError:
            return None, None
        try:
            published = await self.js.get_last_msg("EIP_BATCH", f"eip.batch.result.{correlation_id}")
            return state, json.loads(published.data)["result"]
        except NotFoundError:
            return state, None

    async def ledger_state(self):
        try:
            return json.loads((await self.ledger.get("ledger")).value)
        except NotFoundError:
            return {"total": 0, "applied": []}

    async def status(self):
        """What the broker holds: the ground truth for every pattern."""
        async def stream(name):
            return (await self.js.stream_info(name)).state

        async def acked(stream_name, durable):
            return (await self.js.consumer_info(stream_name, durable)).ack_floor.consumer_seq

        async def subjects(name, pattern):
            return (await self.js.stream_info(name, subjects_filter=pattern)).state.subjects or {}

        orders = await subjects("EIP_ORDERS", "eip.orders.>")
        return {
            "work_queue": {"pending": (await stream("EIP_WORK")).messages},
            "dead_letter": {"messages": (await stream("EIP_DLQ")).messages},
            "publish_subscribe": {name: await acked("EIP_EVENTS", name) for name in SUBSCRIBERS},
            "idempotent_receiver": {
                "stored": (await stream("EIP_PAYMENTS")).messages,
                "processed_payments": len((ledger := await self.ledger_state())["applied"]),
                "ledger_total": ledger["total"],
            },
            "content_based_router": {
                lane: orders.get(f"eip.orders.{lane}", 0) for lane in ("priority", "standard")
            },
            "splitter_aggregator": {
                "batches": len(await subjects("KV_eip_aggregates", "$KV.eip_aggregates.>"))
            },
        }


def valid_id(value):
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None
