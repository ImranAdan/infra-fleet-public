"""Integration patterns against a real nats-server with JetStream.

Each test starts its own broker, drives a pattern through the HTTP API the way
a user does, and asserts on what the broker holds. Set NATS_SERVER to the
binary (CI pins one); without it these tests skip, unless REQUIRE_NATS=1.
"""

import os
import shutil
import socket
import subprocess
import time

import pytest

from load_harness.app import create_app

SERVER = os.environ.get("NATS_SERVER") or shutil.which("nats-server")
if not SERVER:
    if os.environ.get("REQUIRE_NATS") == "1":
        raise RuntimeError("REQUIRE_NATS=1 but no nats-server: set NATS_SERVER")
    pytest.skip("nats-server not installed (set NATS_SERVER)", allow_module_level=True)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def broker(tmp_path):
    port = _free_port()
    process = subprocess.Popen(
        [SERVER, "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield f"nats://127.0.0.1:{port}"
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def api(broker):
    app = create_app({"TESTING": True, "NATS_URL": broker})
    messaging = app.extensions["eip"]
    assert messaging.ready.wait(10), messaging.error
    yield app.test_client()
    messaging.close()


def eventually(api, predicate, timeout=15):
    """Poll the broker-backed status until predicate holds; return it."""
    deadline = time.monotonic() + timeout
    while True:
        status = api.get("/api/eip/status").get_json()
        if predicate(status) or time.monotonic() > deadline:
            return status
        time.sleep(0.1)


def test_work_queue_dead_letters_only_poison_after_max_deliveries(api):
    assert api.post("/api/eip/work", json={"count": 5, "poison": 2}).status_code == 202
    status = eventually(api, lambda s: s["dead_letter"]["messages"] == 2 and s["work_queue"]["pending"] == 0)
    assert status["dead_letter"] == {"messages": 2}
    assert status["work_queue"] == {"pending": 0}


def test_publish_subscribe_delivers_every_event_to_each_subscriber(api):
    for kind in ("created", "updated", "deleted"):
        assert api.post("/api/eip/events", json={"type": kind}).status_code == 202
    status = eventually(api, lambda s: s["publish_subscribe"] == {"audit": 3, "notify": 3})
    assert status["publish_subscribe"] == {"audit": 3, "notify": 3}


def test_idempotent_receiver_processes_a_payment_once(api):
    first = api.post("/api/eip/payments", json={"payment_id": "p1", "amount": 10}).get_json()
    again = api.post("/api/eip/payments", json={"payment_id": "p1", "amount": 10}).get_json()
    assert (first["broker_duplicate"], again["broker_duplicate"]) == (False, True)
    # A new message id passes the broker, so the consumer's guard must catch it.
    retry = {"payment_id": "p1", "amount": 10, "message_id": "p1-retry"}
    assert api.post("/api/eip/payments", json=retry).get_json()["broker_duplicate"] is False
    status = eventually(api, lambda s: s["idempotent_receiver"]["stored"] == 2)
    time.sleep(1)  # give the ledger time to process both stored messages
    status = api.get("/api/eip/status").get_json()
    assert status["idempotent_receiver"] == {"stored": 2, "processed_payments": 1, "ledger_total": 10}


def test_content_based_router_sends_orders_by_priority(api):
    orders = [{"id": f"o{i}", "priority": "high" if i < 3 else "standard"} for i in range(5)]
    assert api.post("/api/eip/orders", json={"orders": orders}).status_code == 202
    status = eventually(api, lambda s: sum(s["content_based_router"].values()) == 5)
    assert status["content_based_router"] == {"priority": 3, "standard": 2}


def test_splitter_aggregator_combines_every_part(api):
    correlation_id = api.post("/api/eip/batch", json={"items": [1, 2, 3, 4]}).get_json()["correlation_id"]
    deadline = time.monotonic() + 15
    while (result := api.get(f"/api/eip/batch/{correlation_id}").get_json())["published_result"] is None:
        assert time.monotonic() < deadline, result
        time.sleep(0.1)
    expected = {"complete": True, "parts": 4, "total": 4, "result": 30, "published_result": 30}
    assert result == {"correlation_id": correlation_id, **expected}


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/eip/work", {"count": 0}),
        ("/api/eip/work", {"count": 2, "poison": 3}),
        ("/api/eip/events", {"type": "a.b"}),
        ("/api/eip/payments", {"payment_id": "../x", "amount": 1}),
        ("/api/eip/payments", {"payment_id": "p", "amount": True}),
        ("/api/eip/orders", {"orders": [{"id": "o", "priority": "urgent"}]}),
        ("/api/eip/batch", {"items": ["1"]}),
    ],
)
def test_rejects_invalid_input(api, path, body):
    assert api.post(path, json=body).status_code == 400
