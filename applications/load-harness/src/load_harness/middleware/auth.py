"""API Key authentication middleware with session support."""

import hmac
import os

from flask import jsonify, request, session

# Exact endpoints that bypass authentication
PUBLIC_ENDPOINTS = frozenset([
    "/health",
    "/ready",
    "/metrics",  # Prometheus scraping
    "/ui/login",  # Login page must be accessible
    "/apidocs",  # Swagger UI
    "/apispec.json",  # OpenAPI spec
])

# Prefixes that bypass authentication
PUBLIC_PREFIXES = (
    "/flasgger_static/",  # Swagger static assets
)


def init_auth(app, config_override=None):
    """Initialize API key authentication middleware.

    Authentication can be satisfied by either:
    - Valid session cookie (for browser users who logged in via /ui/login)
    - Valid X-API-Key header (for API clients)

    Public endpoints that bypass authentication:
    - /health, /ready (K8s probes)
    - /ui/login (login page)
    - /flasgger_static/* (Swagger assets)

    If API_KEY is not set, authentication is disabled (dev mode).

    Args:
        app: Flask application instance
        config_override: Optional config dict (for testing)
    """
    # Load API key from config override or environment
    # If config_override explicitly sets API_KEY (even to None), use that value
    if config_override is not None and "API_KEY" in config_override:
        api_key = config_override["API_KEY"]
    else:
        api_key = os.getenv("API_KEY")
    app.config["API_KEY"] = api_key

    if api_key:
        app.logger.info("API key authentication enabled (session + header)")
    else:
        app.logger.info("API key authentication disabled (API_KEY not set)")

    @app.before_request
    def authenticate():
        """Check session or API key for protected endpoints."""
        api_key = app.config.get("API_KEY")

        # Auth disabled if no API_KEY configured
        if not api_key:
            return None

        # Skip auth for public endpoints
        if request.path in PUBLIC_ENDPOINTS:
            return None
        if request.path.startswith(PUBLIC_PREFIXES):
            return None

        # Check 1: Valid session (browser users who logged in)
        if session.get("authenticated"):
            return None

        # Check 2: Valid X-API-Key header (API clients)
        # Use hmac.compare_digest for timing-safe comparison (prevents timing attacks)
        provided_key = request.headers.get("X-API-Key")
        if provided_key and hmac.compare_digest(provided_key, api_key):
            return None

        # Neither session nor valid API key - unauthorized
        app.logger.warning(
            "Unauthorized request to %s from %s", request.path, request.remote_addr
        )

        # For root path, redirect to login page (user-friendly entry point)
        if request.path == "/":
            from flask import redirect, url_for
            return redirect(url_for("dashboard.login"))

        # For UI routes, redirect to login page
        if request.path.startswith("/ui/"):
            from flask import redirect, url_for
            return redirect(url_for("dashboard.login"))

        # For API routes, return JSON error
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "message": "Valid API key required in X-API-Key header",
                }
            ),
            401,
        )
