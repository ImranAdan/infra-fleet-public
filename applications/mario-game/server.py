"""Serve Fleet Runner's static files. Standard library only."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/game.js": ("game.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
BODIES = {path: (ROOT / name).read_bytes() for path, (name, _) in FILES.items()}
# The fleet's rollback test sets this to make every page request fail; probes
# keep answering so the pods stay ready while the canary analysis sees errors.
FAULT = os.environ.get("GAME_FAULT") == "true"
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/healthz", "/readyz"):
            self.reply(200, b"ok\n", "text/plain")
        elif FAULT:
            self.reply(500, b"fault injected\n", "text/plain")
        elif path in FILES:
            self.reply(200, BODIES[path], FILES[path][1])
        else:
            self.reply(404, b"not found\n", "text/plain")

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("", port), Handler).serve_forever()
