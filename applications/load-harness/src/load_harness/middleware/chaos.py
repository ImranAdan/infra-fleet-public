"""Chaos/fault injection middleware for testing resilience."""

import os
import random

from flask import jsonify, request

# Endpoints that never fail (K8s probes must always work)
PROTECTED_ENDPOINTS = frozenset(["/health", "/ready"])

# Prefixes that never fail (UI must remain functional for users)
PROTECTED_PREFIXES = ("/ui/", "/flasgger_static/")


def init_chaos(app, config_override=None):
    """Initialize chaos injection middleware.

    When FAIL_RATE environment variable (or config override) is set to a value
    between 0.0 and 1.0, requests to non-protected endpoints will randomly fail
    with a 500 error.

    This is useful for testing Flagger canary rollbacks and system resilience.

    Args:
        app: Flask application instance
        config_override: Optional config dict (for testing)
    """
    # Load fail rate from config override or environment
    try:
        fail_rate = float(
            (config_override or {}).get("FAIL_RATE") or os.getenv("FAIL_RATE", "0.0")
        )
        # Clamp to 0.0-1.0 range
        fail_rate = max(0.0, min(1.0, fail_rate))
    except (ValueError, TypeError):
        fail_rate = 0.0

    app.config["FAIL_RATE"] = fail_rate

    if fail_rate > 0.0:
        app.logger.warning("Chaos injection enabled with FAIL_RATE=%s", fail_rate)
    else:
        app.logger.info("Chaos injection disabled (FAIL_RATE=0.0)")

    @app.before_request
    def chaos_injection():
        """Randomly fail requests for chaos testing."""
        fail_rate = app.config.get("FAIL_RATE", 0.0)

        # No chaos if rate is 0
        if fail_rate <= 0.0:
            return None

        # Never fail protected endpoints (K8s probes)
        if request.path in PROTECTED_ENDPOINTS:
            return None

        # Never fail UI routes (user experience must remain stable)
        if request.path == "/ui" or request.path.startswith(PROTECTED_PREFIXES):
            return None

        # Roll the dice
        if random.random() < fail_rate:
            app.logger.warning(
                "Chaos injection triggered: path=%s rate=%s", request.path, fail_rate
            )
            return (
                jsonify(
                    {
                        "error": "Chaos injection triggered",
                        "message": f"Intentional failure for testing (FAIL_RATE={fail_rate})",
                        "chaos": True,
                    }
                ),
                500,
            )

        return None
