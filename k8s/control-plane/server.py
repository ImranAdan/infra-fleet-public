"""Fleet control plane: the application dashboard. Standard library only.

Lists every app from its contract at the deployed revision (the fleet-catalog
ConfigMap the facade publishes) with its live state, launches a sleeping app on
demand, stops a launched one, and proxies http://<app>.localhost:9000 to it.

Launching never edits workloads: it asks Flux to deploy the app from Git, as
two Kustomizations (the app's manifests and the shared platform templates,
filled with the app's contract) that run as the app-deployer service account.
That identity can change application workloads and app-owned Grafana dashboard
ConfigMaps; it has no cluster-wide grant. Stopping deletes the Kustomizations
and Flux prunes the stack.

A launched app goes back to sleep: a background sweep stops any launched app
that no proxied request has reached for IDLE_MINUTES (0 disables it).
"""

import http.client
import io
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
API = "https://kubernetes.default.svc"
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
KUSTOMIZATIONS = "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/flux-system/kustomizations"
GATEWAY = "fleet-gateway.envoy-gateway-system"
TRUST = Path("/etc/fleet-trust/ca.crt")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_LINE = re.compile(r"^  (APP_[A-Z_]+):\s*(.*)$")
_APP_HOST = re.compile(r"^([a-z0-9]([-a-z0-9]*[a-z0-9])?)\.localhost(:\d+)?$")
_CONTROL_HOST = re.compile(r"^localhost(:\d+)?$")
IDLE_MINUTES = float(os.environ.get("IDLE_MINUTES", "30"))
# Monotonic time of each app's last proxied request or launch. In memory only:
# after a restart an app has no entry, and its first sighting starts a fresh
# grace period rather than stopping it at once.
last_seen: dict[str, float] = {}
_LAUNCH_SUBSTITUTIONS = (
    "APP_NAME",
    "APP_PORT",
    "APP_HEALTH_PATH",
    "APP_LOAD_PATH",
)


def forwardable_headers(
    headers: list[tuple[str, str]], extra: set[str] | frozenset[str] = frozenset()
) -> list[tuple[str, str]]:
    """Remove fixed and Connection-nominated hop-by-hop fields."""
    nominated = {
        token.strip().lower()
        for name, value in headers
        if name.lower() == "connection"
        for token in value.split(",")
        if token.strip()
    }
    blocked = HOP_BY_HOP | nominated | {name.lower() for name in extra}
    return [(name, value) for name, value in headers if name.lower() not in blocked]


def contract(text: str) -> dict[str, str]:
    """The APP_* values of one contract ConfigMap, as the facade's awk reads them."""
    values = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            values[match[1]] = match[2].strip().strip('"')
    return values


def app_state(name: str, canaries: dict, deployments: dict, launching: bool = False) -> str:
    """running: serving from its primary; starting: launched or partly deployed
    but not serving yet; sleeping: nothing of it is deployed."""
    if name not in canaries and name not in deployments:
        return "starting" if launching else "sleeping"
    ready = deployments.get(f"{name}-primary", {}).get("readyReplicas", 0)
    phase = canaries.get(name, {}).get("phase", "")
    return "running" if ready and phase not in ("", "Initializing") else "starting"


def catalogue(
    catalog: dict, canaries: dict, deployments: dict, selected: str, launched: set[str]
) -> list[dict]:
    apps = []
    for key, text in sorted(catalog.items()):
        values = contract(text)
        name = values.get("APP_NAME", key)
        apps.append(
            {
                "name": name,
                "title": values.get("APP_TITLE") or name,
                "description": values.get("APP_DESCRIPTION", ""),
                "state": app_state(name, canaries, deployments, name in launched),
                "phase": canaries.get(name, {}).get("phase", ""),
                "selected": name == selected,
                # The default app belongs to the fleet's own layer: never offer
                # Stop for it, even if it was launched before being selected.
                "launched": name in launched and name != selected,
            }
        )
    return apps


def kustomizations(values: dict[str, str]) -> list[dict]:
    """The two Flux Kustomizations that deploy one app from Git: its manifests,
    and the shared platform templates (canary, HPA, NetworkPolicy)."""
    name = values["APP_NAME"]
    substitute = {key: values[key] for key in _LAUNCH_SUBSTITUTIONS}
    substitute["APP_HOSTNAME"] = route_host(name)
    common = {
        "interval": "1m",
        "prune": True,
        "wait": False,
        "timeout": "10m",
        "serviceAccountName": "app-deployer",
        "sourceRef": {"kind": "GitRepository", "name": "fleet-local"},
        "postBuild": {
            "substitute": substitute,
            "substituteFrom": [{"kind": "ConfigMap", "name": "fleet-config"}],
        },
    }
    labels = {"infra-fleet.io/launched-app": name}
    return [
        {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
            "kind": "Kustomization",
            "metadata": {"name": f"app-{name}", "namespace": "flux-system", "labels": labels},
            "spec": {
                **common,
                "path": f"./k8s/applications/{name}",
                # Every app's image is named `app`; bind it to this app's build.
                "images": [
                    {"name": "app", "newName": "${IMAGE_REGISTRY}/" + name, "newTag": "${IMAGE_TAG}"}
                ],
            },
        },
        {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
            "kind": "Kustomization",
            "metadata": {
                "name": f"app-{name}-platform",
                "namespace": "flux-system",
                "labels": labels,
            },
            "spec": {
                **common,
                "path": "./k8s/applications/platform",
                "dependsOn": [{"name": f"app-{name}"}],
                # The local profile's HPA ceiling, as for the selected app.
                "patches": [
                    {
                        "target": {"kind": "HorizontalPodAutoscaler"},
                        "patch": '[{"op": "replace", "path": "/spec/maxReplicas", "value": 3}]',
                    }
                ],
            },
        },
    ]


def app_for_host(host: str, catalog_names: set[str]) -> str | None:
    """The catalogued app a Host header addresses, as <app>.localhost[:port]."""
    match = _APP_HOST.match(host or "")
    return match[1] if match and match[1] in catalog_names else None


def control_host(host: str) -> bool:
    """Whether a request uses the dashboard's documented loopback name.

    A loopback-bound port-forward alone does not prevent DNS rebinding: a
    hostile origin can resolve its own name to 127.0.0.1. Requiring localhost
    closes that same-origin browser path.
    """
    return bool(_CONTROL_HOST.fullmatch(host or ""))


def route_host(app: str) -> str:
    """A launched app's route host. Two labels after the certificate's wildcard
    (*.apps.localhost): TLS clients reject a wildcard directly over a single
    label such as *.localhost. People still browse to <app>.localhost:9000."""
    return f"{app}.apps.localhost"


def gateway_host(app: str, selected: str) -> str:
    """The host an app's route answers on: the selected app keeps the fleet's
    base host, and every launched app has its own."""
    return "localhost" if app == selected else route_host(app)


class GatewayConnection(http.client.HTTPSConnection):
    """HTTPS to the fleet Gateway, verifying its certificate for the app's host
    name (sent as SNI) against the fleet's local CA."""

    def __init__(self, host: str) -> None:
        context = ssl.create_default_context(cafile=str(TRUST))
        super().__init__(GATEWAY, 443, context=context, timeout=30)
        self.app_host = host

    def connect(self) -> None:
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.app_host)


def kube(path: str, method: str = "GET", body: dict | None = None) -> dict:
    token = (SA / "token").read_text().strip()
    request = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    context = ssl.create_default_context(cafile=str(SA / "ca.crt"))
    with urllib.request.urlopen(request, context=context, timeout=10) as response:  # noqa: S310
        return json.load(response)


def read_catalog() -> tuple[dict, str]:
    catalog = kube("/api/v1/namespaces/flux-system/configmaps/fleet-catalog")["data"]
    selected = kube("/api/v1/namespaces/flux-system/configmaps/fleet-app")["data"]["APP_NAME"]
    return catalog, selected


def launched_apps() -> set[str]:
    items = kube(f"{KUSTOMIZATIONS}?labelSelector=infra-fleet.io/launched-app")["items"]
    return {item["metadata"]["labels"]["infra-fleet.io/launched-app"] for item in items}


def live_apps() -> list[dict]:
    catalog, selected = read_catalog()
    canaries = {
        item["metadata"]["name"]: item.get("status", {})
        for item in kube("/apis/flagger.app/v1beta1/namespaces/applications/canaries")["items"]
    }
    deployments = {
        item["metadata"]["name"]: item.get("status", {})
        for item in kube("/apis/apps/v1/namespaces/applications/deployments")["items"]
    }
    apps = catalogue(catalog, canaries, deployments, selected, launched_apps())
    now = time.monotonic()
    for app in apps:
        app["sleeps_in"] = sleeps_in(app["name"], now) if app["launched"] else None
    return apps


def sleeps_in(name: str, now: float) -> int | None:
    """Whole minutes until the idle sweep stops a launched app; None if disabled."""
    if not IDLE_MINUTES:
        return None
    left = last_seen.setdefault(name, now) + IDLE_MINUTES * 60 - now
    return max(0, -int(-left // 60))


def sweep(now: float) -> None:
    """Stop every launched app, never the selected one, idle past IDLE_MINUTES."""
    if not IDLE_MINUTES:
        return
    _, selected = read_catalog()
    for name in launched_apps() - {selected}:
        if now - last_seen.setdefault(name, now) > IDLE_MINUTES * 60:
            print(f"stopping {name}: idle for over {IDLE_MINUTES:g} min", flush=True)
            stop(name)
            last_seen.pop(name, None)


def sleeper() -> None:
    while True:
        time.sleep(60)
        try:
            sweep(time.monotonic())
        except Exception as exc:  # noqa: BLE001 - keep sweeping after a failed pass
            print(f"idle sweep failed: {exc}", file=sys.stderr, flush=True)


def launch(name: str) -> None:
    catalog, selected = read_catalog()
    texts = {contract(text).get("APP_NAME"): text for text in catalog.values()}
    if name not in texts or name == selected:
        raise ValueError(f"{name} is not a launchable app")
    values = contract(texts[name])
    missing = [key for key in _LAUNCH_SUBSTITUTIONS if not values.get(key)]
    if missing:
        raise ValueError(f"{name} has an incomplete contract: {', '.join(missing)}")
    for body in kustomizations(values):
        try:
            kube(KUSTOMIZATIONS, "POST", body)
        except urllib.error.HTTPError as exc:
            if exc.code != 409:
                raise
            # 409 means it exists: fine if launched, but a stop still being
            # finalised would silently swallow this launch.
            existing = kube(f"{KUSTOMIZATIONS}/{body['metadata']['name']}")
            if existing.get("metadata", {}).get("deletionTimestamp"):
                raise ValueError(f"{name} is still stopping; launch it again shortly") from exc
    last_seen[name] = time.monotonic()


def stop(name: str) -> None:
    _, selected = read_catalog()
    if name == selected:
        raise ValueError(f"{name} is the fleet's default app and cannot be stopped here")
    if name not in launched_apps():
        raise ValueError(f"{name} was not launched from the dashboard")
    for suffix in ("-platform", ""):
        try:
            kube(f"{KUSTOMIZATIONS}/app-{name}{suffix}", "DELETE")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:  # a launch that failed half-way has one part
                raise


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.route()

    def do_POST(self) -> None:
        self.route()

    def do_PUT(self) -> None:
        self.route()

    def do_DELETE(self) -> None:
        self.route()

    def route(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/healthz", "/readyz"):
            return self.reply(200, b"ok\n", "text/plain")
        try:
            catalog, selected = read_catalog()
        except (OSError, KeyError, ValueError) as exc:
            return self.reply(503, json.dumps({"error": str(exc)}).encode(), "application/json")
        names = {contract(text).get("APP_NAME") for text in catalog.values()}
        app = app_for_host(self.headers.get("Host", ""), names)
        if app:
            last_seen[app] = time.monotonic()
            return self.proxy(gateway_host(app, selected))
        if not control_host(self.headers.get("Host", "")):
            return self.reply(421, b"dashboard requires a localhost Host header\n", "text/plain")
        if self.command == "GET" and path == "/api/apps":
            try:
                return self.reply(200, json.dumps({"apps": live_apps()}).encode(), "application/json")
            except (OSError, KeyError, ValueError) as exc:
                return self.reply(503, json.dumps({"error": str(exc)}).encode(), "application/json")
        action = re.fullmatch(r"/api/apps/([a-z0-9-]+)/(launch|stop)", path)
        if self.command == "POST" and action:
            # A custom header cannot be sent cross-site without a CORS preflight,
            # which this server never grants, so other sites cannot drive it.
            if self.headers.get("X-Fleet-Action") != "1":
                return self.reply(403, b"missing X-Fleet-Action\n", "text/plain")
            try:
                (launch if action[2] == "launch" else stop)(action[1])
                return self.reply(202, b'{"ok": true}', "application/json")
            except (ValueError, OSError) as exc:
                return self.reply(409, json.dumps({"error": str(exc)}).encode(), "application/json")
        if self.command == "GET" and path in STATIC:
            name, content_type = STATIC[path]
            return self.reply(200, (ROOT / name).read_bytes(), content_type)
        self.reply(404, b"not found\n", "text/plain")

    def proxy(self, host: str) -> None:
        """Forward to the app through the Gateway, the declared ingress, over TLS
        verified against the fleet's local CA for the app's own host name."""
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = dict(forwardable_headers(list(self.headers.items()), {"host"}))
        headers["Host"] = host
        connection = GatewayConnection(host)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
        except OSError as exc:
            return self.reply(502, f"{host} is not reachable yet: {exc}\n".encode(), "text/plain")
        finally:
            connection.close()
        self.send_response(response.status)
        for name, value in forwardable_headers(response.getheaders(), {"content-length"}):
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def self_test() -> None:
    text = '''apiVersion: v1
data:
  APP_NAME: game
  APP_TITLE: "Fleet Runner"
  APP_PORT: "8080"
  APP_HEALTH_PATH: /healthz
  APP_LOAD_PATH: /
'''
    assert contract(text) == {
        "APP_NAME": "game",
        "APP_TITLE": "Fleet Runner",
        "APP_PORT": "8080",
        "APP_HEALTH_PATH": "/healthz",
        "APP_LOAD_PATH": "/",
    }
    serving = {"game-primary": {"readyReplicas": 1}}
    assert app_state("game", {"game": {"phase": "Succeeded"}}, serving) == "running"
    assert app_state("game", {"game": {"phase": "Initializing"}}, serving) == "starting"
    assert app_state("game", {"game": {"phase": "Succeeded"}}, {}) == "starting"
    assert app_state("game", {}, {}) == "sleeping"
    assert app_state("game", {}, {}, launching=True) == "starting"
    apps = catalogue({"game": text, "b": "  APP_NAME: b\n"}, {}, {}, "game", {"b"})
    assert [(a["name"], a["title"], a["selected"], a["launched"], a["state"]) for a in apps] == [
        ("b", "b", False, True, "starting"),
        ("game", "Fleet Runner", True, False, "sleeping"),
    ]

    app, platform = kustomizations(contract(text))
    assert app["metadata"]["name"] == "app-game" and platform["metadata"]["name"] == "app-game-platform"
    assert app["spec"]["path"] == "./k8s/applications/game"
    assert platform["spec"]["path"] == "./k8s/applications/platform"
    assert platform["spec"]["dependsOn"] == [{"name": "app-game"}]
    for body in (app, platform):
        spec = body["spec"]
        assert spec["serviceAccountName"] == "app-deployer"
        assert spec["postBuild"]["substitute"]["APP_HOSTNAME"] == "game.apps.localhost"
        assert spec["postBuild"]["substitute"]["APP_PORT"] == "8080"
        assert set(spec["postBuild"]["substitute"]) == {
            "APP_NAME",
            "APP_PORT",
            "APP_HEALTH_PATH",
            "APP_LOAD_PATH",
            "APP_HOSTNAME",
        }
        assert body["metadata"]["labels"] == {"infra-fleet.io/launched-app": "game"}
    assert app["spec"]["images"][0]["newName"] == "${IMAGE_REGISTRY}/game"

    names = {"game", "sample"}
    assert app_for_host("game.localhost:9000", names) == "game"
    assert app_for_host("sample.localhost", names) == "sample"
    assert app_for_host("localhost:9000", names) is None
    assert app_for_host("evil.localhost:9000", names) is None
    assert app_for_host("game.localhost.evil.test", names) is None
    assert control_host("localhost")
    assert control_host("localhost:9000")
    assert not control_host("127.0.0.1:9000")
    assert not control_host("dashboard.example:9000")
    assert gateway_host("game", selected="game") == "localhost"
    assert gateway_host("sample", selected="game") == "sample.apps.localhost"

    assert forwardable_headers(
        [
            ("Connection", "X-Internal, keep-alive"),
            ("X-Internal", "must not cross the proxy"),
            ("Trailer", "Digest"),
            ("X-End-To-End", "kept"),
        ],
        {"host"},
    ) == [("X-End-To-End", "kept")]

    # The default app never offers Stop, even if it was launched earlier.
    [row] = catalogue({"game": text}, {}, {}, "game", {"game"})
    assert row["launched"] is False

    # Launch and stop against a fake API, for the review's failure scenarios.
    global kube, read_catalog, launched_apps, stop, IDLE_MINUTES, GatewayConnection
    real = (kube, read_catalog, launched_apps, stop, IDLE_MINUTES)
    calls: list[tuple[str, str]] = []
    responses: dict[tuple[str, str], object] = {}

    def fake_kube(path: str, method: str = "GET", body: dict | None = None) -> dict:
        calls.append((method, path))
        result = responses.get((method, path.rsplit("/", 1)[-1]), {})
        if isinstance(result, int):
            raise urllib.error.HTTPError(path, result, "status", None, None)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]

    sample_text = text.replace("APP_NAME: game", "APP_NAME: sample")
    kube, read_catalog = fake_kube, lambda: ({"s": "  APP_NAME: sample\n"}, "game")
    launched_apps = lambda: {"sample"}  # noqa: E731
    try:
        # A catalog entry without every value used by the shared platform is
        # visible but cannot create a partial launch object.
        try:
            launch("sample")
            raise AssertionError("an incomplete contract was launched")
        except ValueError as exc:
            assert "incomplete contract" in str(exc)
        read_catalog = lambda: ({"s": sample_text}, "game")  # noqa: E731
        # Relaunching while the previous stop is still finalising is an error.
        responses = {("POST", "kustomizations"): 409,
                     ("GET", "app-sample"): {"metadata": {"deletionTimestamp": "now"}}}
        try:
            launch("sample")
            raise AssertionError("a launch during a pending stop was accepted")
        except ValueError as exc:
            assert "still stopping" in str(exc)
        # Already launched and live: a no-op, not an error.
        responses = {("POST", "kustomizations"): 409, ("GET", "app-sample"): {"metadata": {}},
                     ("GET", "app-sample-platform"): {"metadata": {}}}
        launch("sample")
        # Stop tolerates a half-launched app whose platform part never existed.
        calls.clear()
        responses = {("DELETE", "app-sample-platform"): 404}
        stop("sample")
        assert ("DELETE", f"{KUSTOMIZATIONS}/app-sample") in calls
        # The default app cannot be stopped from the dashboard.
        read_catalog = lambda: ({}, "sample")  # noqa: E731
        try:
            stop("sample")
            raise AssertionError("stopping the default app was accepted")
        except ValueError:
            pass
        # Idle sweep on a fake clock. "game" is selected, so never stopped.
        stopped: list[str] = []
        stop = stopped.append
        read_catalog = lambda: ({}, "game")  # noqa: E731
        launched_apps = lambda: {"game", "idle", "busy", "new"}  # noqa: E731
        IDLE_MINUTES = 30
        last_seen.clear()
        last_seen.update({"game": 0.0, "idle": 0.0, "busy": 0.0})
        assert sleeps_in("idle", 60.0) == 29
        last_seen["busy"] = 1500.0  # recent proxied traffic
        sweep(1801.0)  # "new" has no record, as after a restart: grace starts now
        assert stopped == ["idle"] and "idle" not in last_seen
        assert last_seen["new"] == 1801.0 and sleeps_in("new", 1801.0) == 30
        sweep(1801.0 + 1800 + 1)
        assert sorted(stopped) == ["busy", "idle", "new"]
        stopped.clear()
        IDLE_MINUTES = 0
        last_seen.clear()
        sweep(10**9)
        assert stopped == [] and sleeps_in("busy", 10**9) is None
    finally:
        kube, read_catalog, launched_apps, stop, IDLE_MINUTES = real
        last_seen.clear()

    # The app proxy streams in both directions. Whole-body buffering can OOM
    # this 64 MiB control-plane pod when a contracted app transfers a large
    # request or response.
    real_gateway = GatewayConnection
    request_body = b"request-body"
    response_body = b"response-body"
    forwarded: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __init__(self) -> None:
            self.body = io.BytesIO(response_body)

        def getheaders(self) -> list[tuple[str, str]]:
            return [
                ("Content-Length", str(len(response_body))),
                ("Connection", "X-Upstream-Hop"),
                ("X-Upstream-Hop", "drop"),
                ("X-End-To-End", "kept"),
            ]

        def read(self, size: int = -1) -> bytes:
            assert size > 0, "the proxy buffered the complete upstream response"
            return self.body.read(min(size, 3))

    class FakeGateway:
        def __init__(self, host: str) -> None:
            forwarded["gateway"] = host

        def request(self, method: str, path: str, body: object, headers: dict[str, str]) -> None:
            chunks = []
            while True:
                chunk = body.read(3)  # type: ignore[attr-defined]
                if not chunk:
                    break
                chunks.append(chunk)
            forwarded.update(method=method, path=path, body=b"".join(chunks), headers=headers)

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            forwarded["closed"] = True

    handler = object.__new__(Handler)
    handler.command = "PATCH"
    handler.path = "/upload?part=1"
    handler.rfile = io.BytesIO(request_body)
    handler.wfile = io.BytesIO()
    handler.headers = http.client.HTTPMessage()
    handler.headers["Content-Length"] = str(len(request_body))
    handler.headers["Connection"] = "X-Request-Hop"
    handler.headers["X-Request-Hop"] = "drop"
    handler.headers["X-End-To-End"] = "kept"
    response_headers: list[tuple[str, str]] = []
    handler.send_response = lambda status: forwarded.update(status=status)  # type: ignore[method-assign]
    handler.send_header = lambda name, value: response_headers.append((name, value))  # type: ignore[method-assign]
    handler.end_headers = lambda: None  # type: ignore[method-assign]
    GatewayConnection = FakeGateway  # type: ignore[misc,assignment]
    try:
        handler.proxy("game.apps.localhost")
    finally:
        GatewayConnection = real_gateway
    assert forwarded == {
        "gateway": "game.apps.localhost",
        "method": "PATCH",
        "path": "/upload?part=1",
        "body": request_body,
        "headers": {
            "Content-Length": str(len(request_body)),
            "X-End-To-End": "kept",
            "Host": "game.apps.localhost",
        },
        "status": 200,
        "closed": True,
    }
    assert response_headers == [
        ("Content-Length", str(len(response_body))),
        ("X-End-To-End", "kept"),
    ]
    assert handler.wfile.getvalue() == response_body
    print("self-test passed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        threading.Thread(target=sleeper, daemon=True).start()
        ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
