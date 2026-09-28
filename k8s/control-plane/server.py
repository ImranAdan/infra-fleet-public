"""Fleet control plane: the application dashboard. Standard library only.

Reads the app catalogue (every contract at the deployed revision, published by
the facade as the fleet-catalog ConfigMap) and each app's live state from the
Kubernetes API. Read-only: it never changes the cluster.
"""

import json
import os
import re
import ssl
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
API = "https://kubernetes.default.svc"
SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
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
_LINE = re.compile(r"^  (APP_[A-Z_]+):\s*(.*)$")


def contract(text: str) -> dict[str, str]:
    """The APP_* values of one contract ConfigMap, as the facade's awk reads them."""
    values = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            values[match[1]] = match[2].strip().strip('"')
    return values


def app_state(name: str, canaries: dict, deployments: dict) -> str:
    """running: serving from its primary; starting: its stack exists but is not
    serving yet; sleeping: nothing of it is deployed."""
    if name not in canaries and name not in deployments:
        return "sleeping"
    ready = deployments.get(f"{name}-primary", {}).get("readyReplicas", 0)
    phase = canaries.get(name, {}).get("phase", "")
    return "running" if ready and phase not in ("", "Initializing") else "starting"


def catalogue(catalog: dict, canaries: dict, deployments: dict, selected: str) -> list[dict]:
    apps = []
    for key, text in sorted(catalog.items()):
        values = contract(text)
        name = values.get("APP_NAME", key)
        apps.append(
            {
                "name": name,
                "title": values.get("APP_TITLE") or name,
                "description": values.get("APP_DESCRIPTION", ""),
                "state": app_state(name, canaries, deployments),
                "phase": canaries.get(name, {}).get("phase", ""),
                "selected": name == selected,
            }
        )
    return apps


def kube(path: str) -> dict:
    token = (SA / "token").read_text().strip()
    request = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {token}"})
    context = ssl.create_default_context(cafile=str(SA / "ca.crt"))
    with urllib.request.urlopen(request, context=context, timeout=5) as response:  # noqa: S310
        return json.load(response)


def live_apps() -> list[dict]:
    catalog = kube("/api/v1/namespaces/flux-system/configmaps/fleet-catalog")["data"]
    selected = kube("/api/v1/namespaces/flux-system/configmaps/fleet-app")["data"]["APP_NAME"]
    canaries = {
        item["metadata"]["name"]: item.get("status", {})
        for item in kube("/apis/flagger.app/v1beta1/namespaces/applications/canaries")["items"]
    }
    deployments = {
        item["metadata"]["name"]: item.get("status", {})
        for item in kube("/apis/apps/v1/namespaces/applications/deployments")["items"]
    }
    return catalogue(catalog, canaries, deployments, selected)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/healthz", "/readyz"):
            self.reply(200, b"ok\n", "text/plain")
        elif path == "/api/apps":
            try:
                body = json.dumps({"apps": live_apps()}).encode()
                self.reply(200, body, "application/json")
            except (OSError, KeyError, ValueError) as exc:
                self.reply(503, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif path in STATIC:
            name, content_type = STATIC[path]
            self.reply(200, (ROOT / name).read_bytes(), content_type)
        else:
            self.reply(404, b"not found\n", "text/plain")

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
'''
    assert contract(text) == {"APP_NAME": "game", "APP_TITLE": "Fleet Runner", "APP_PORT": "8080"}
    serving = {"game-primary": {"readyReplicas": 1}}
    assert app_state("game", {"game": {"phase": "Succeeded"}}, serving) == "running"
    assert app_state("game", {"game": {"phase": "Initializing"}}, serving) == "starting"
    assert app_state("game", {"game": {"phase": "Succeeded"}}, {}) == "starting"
    assert app_state("game", {}, {}) == "sleeping"
    apps = catalogue({"game": text, "b": "  APP_NAME: b\n"}, {}, {}, "game")
    assert [(a["name"], a["title"], a["selected"]) for a in apps] == [
        ("b", "b", False),
        ("game", "Fleet Runner", True),
    ]
    print("self-test passed")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
