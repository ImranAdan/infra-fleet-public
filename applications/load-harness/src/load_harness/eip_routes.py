"""HTTP drivers for the integration patterns in messaging.py.

Every route answers 503 unless NATS_URL configured a broker, so the app runs
unchanged on a platform without one.
"""

from flask import Blueprint, current_app, jsonify, request

from load_harness.messaging import MessagingUnavailable, valid_id

eip = Blueprint("eip", __name__, url_prefix="/api/eip")
MAX_MESSAGES = 100
MAX_VALUE = 1_000_000


def _messaging():
    return current_app.extensions.get("eip")


@eip.before_request
def _require_broker():
    if _messaging() is None:
        return jsonify(error="messaging is not configured (set NATS_URL)"), 503
    return None


@eip.errorhandler(MessagingUnavailable)
def _unavailable(error):
    return jsonify(error=str(error)), 503


def _bad(message):
    return jsonify(error=message), 400


def _int(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


@eip.post("/work")
def work():
    body = request.get_json(silent=True) or {}
    count, poison = body.get("count", 1), body.get("poison", 0)
    if not _int(count, 1, MAX_MESSAGES) or not _int(poison, 0, count):
        return _bad(f"count must be 1-{MAX_MESSAGES} and poison 0-count")
    _messaging().call(_messaging().send_work(count, poison))
    return jsonify(sent=count, poison=poison), 202


@eip.post("/events")
def events():
    kind = (request.get_json(silent=True) or {}).get("type", "")
    if not valid_id(kind):
        return _bad("type must be 1-64 letters, digits, '-' or '_'")
    _messaging().call(_messaging().publish_event(kind))
    return jsonify(published=kind), 202


@eip.post("/payments")
def payments():
    body = request.get_json(silent=True) or {}
    payment_id, amount = body.get("payment_id"), body.get("amount")
    message_id = body.get("message_id", payment_id)
    if not valid_id(payment_id) or not valid_id(message_id):
        return _bad("payment_id and message_id must be 1-64 letters, digits, '-' or '_'")
    if not _int(amount, 1, MAX_VALUE):
        return _bad(f"amount must be an integer 1-{MAX_VALUE}")
    duplicate = _messaging().call(_messaging().send_payment(payment_id, amount, message_id))
    return jsonify(payment_id=payment_id, broker_duplicate=duplicate), 202


@eip.post("/orders")
def orders():
    items = (request.get_json(silent=True) or {}).get("orders")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MESSAGES:
        return _bad(f"orders must be a list of 1-{MAX_MESSAGES}")
    for order in items:
        if not isinstance(order, dict) or not valid_id(order.get("id")):
            return _bad("each order needs an id of letters, digits, '-' or '_'")
        if order.get("priority") not in ("high", "standard"):
            return _bad("priority must be high or standard")
    clean = [{"id": order["id"], "priority": order["priority"]} for order in items]
    _messaging().call(_messaging().send_orders(clean))
    return jsonify(routed=len(clean)), 202


@eip.post("/batch")
def batch():
    items = (request.get_json(silent=True) or {}).get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MESSAGES:
        return _bad(f"items must be a list of 1-{MAX_MESSAGES}")
    if not all(_int(item, -MAX_VALUE, MAX_VALUE) for item in items):
        return _bad(f"items must be integers within ±{MAX_VALUE}")
    correlation_id = _messaging().call(_messaging().send_batch(items))
    return jsonify(correlation_id=correlation_id), 202


@eip.get("/batch/<correlation_id>")
def batch_result(correlation_id):
    if not valid_id(correlation_id):
        return _bad("unknown correlation id")
    state, published = _messaging().call(_messaging().batch_result(correlation_id))
    if state is None:
        return jsonify(correlation_id=correlation_id, complete=False, parts=0, published_result=None)
    return jsonify(
        correlation_id=correlation_id,
        complete="result" in state,
        parts=len(state["parts"]),
        total=state["total"],
        result=state.get("result"),
        published_result=published,
    )


@eip.get("/status")
def status():
    return jsonify(_messaging().call(_messaging().status()))
