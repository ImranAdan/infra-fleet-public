"""Application factory for LoadHarness.

This module bootstraps the Flask application by wiring together:
- Swagger/OpenAPI documentation
- Authentication middleware (API key + session)
- Chaos injection middleware
- Security headers middleware (X-Frame-Options, X-Content-Type-Options, etc.)
- Prometheus metrics
- Route handlers
- Dashboard blueprint
"""

import logging
import os
import secrets
from datetime import timedelta

from flask import Flask
from prometheus_flask_exporter import PrometheusMetrics
from werkzeug.middleware.proxy_fix import ProxyFix

from load_harness.dashboard import dashboard
from load_harness.load_harness_service import LoadHarnessService
from load_harness.middleware import init_auth, init_chaos, init_security_headers
from load_harness.swagger_config import init_swagger


def _configured_api_key(config_override: dict | None) -> str | None:
    """Resolve the API key the same way init_auth does.

    An explicit API_KEY in config_override wins even when it is None, so tests
    can still build an unauthenticated app.
    """
    if config_override is not None and "API_KEY" in config_override:
        return config_override["API_KEY"]
    return os.getenv("API_KEY")


def create_app(config_override: dict | None = None):
    """Application factory for creating the Flask app.

    Args:
        config_override: Optional config dict for testing. Supports:
            - API_KEY: Enable authentication with this key
            - FAIL_RATE: Chaos injection probability (0.0-1.0)
            - SECRET_KEY: Flask secret key for sessions

    Returns:
        Flask application instance
    """
    app = Flask(__name__)

    # ProxyFix: Trust X-Forwarded-* headers from reverse proxy (nginx-ingress)
    # This ensures Flask knows the original protocol (HTTPS) and client IP
    # x_for=1: Trust 1 hop for X-Forwarded-For (client IP)
    # x_proto=1: Trust 1 hop for X-Forwarded-Proto (HTTPS detection)
    # x_host=1: Trust 1 hop for X-Forwarded-Host (original hostname)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Session configuration
    # SECRET_KEY from env, config override, or generate random (dev only)
    secret_key = (
        (config_override or {}).get("SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or secrets.token_hex(32)
    )
    app.config["SECRET_KEY"] = secret_key
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    # Cookie configuration for HTMX compatibility
    # SameSite=Lax ensures cookies are sent with same-origin subrequests (HTMX)
    # Without this, browsers may not send cookies with AJAX/fetch requests
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    # Secure flag: Only send cookie over HTTPS (required for production)
    # Local dev doesn't use HTTPS, so we check the environment
    environment = os.getenv("ENVIRONMENT", "local")
    cookie_secure = os.getenv("SESSION_COOKIE_SECURE")
    if cookie_secure is not None and cookie_secure not in ("true", "false"):
        raise ValueError("SESSION_COOKIE_SECURE must be true or false")
    app.config["SESSION_COOKIE_SECURE"] = (
        environment != "local" if cookie_secure is None else cookie_secure == "true"
    )

    # Base config from environment
    app.config.from_mapping(
        ENVIRONMENT=os.getenv("ENVIRONMENT", "local"),
        APP_VERSION=os.getenv("APP_VERSION", "dev"),
    )

    # Apply config overrides (for testing)
    if config_override:
        app.config.update(config_override)

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    # Initialize Swagger/OpenAPI documentation
    init_swagger(app)

    # Fail closed outside local development. The Kubernetes Secret holding
    # API_KEY is mounted with optional: true, so a renamed or missing Secret
    # used to start the app with authentication silently disabled and every
    # load endpoint reachable through the ingress. Crash-looping is visible;
    # serving openly is not.
    if environment != "local" and not _configured_api_key(config_override):
        raise RuntimeError(
            "API_KEY must be set when ENVIRONMENT is not 'local'. "
            "Refusing to start with authentication disabled."
        )

    # Initialize middleware (order matters: auth runs before chaos)
    init_auth(app, config_override)
    init_chaos(app, config_override)
    init_security_headers(app)

    # Initialize Prometheus metrics
    metrics = PrometheusMetrics(app)

    # Register service (wires all routes)
    LoadHarnessService(app=app, metrics=metrics)

    # Register dashboard blueprint
    app.register_blueprint(dashboard)

    return app


# For local dev: `python -m load_harness.app`
if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
