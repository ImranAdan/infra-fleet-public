"""Swagger/OpenAPI configuration for LoadHarness API."""

import os

from flasgger import Swagger

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs",
}

SWAGGER_TEMPLATE = {
    "info": {
        "title": "LoadHarness API",
        "description": "Synthetic workload generator for Kubernetes platforms. "
        "Provides controlled CPU and memory stress workloads to validate "
        "autoscaling behavior, observability pipelines, and system resilience.",
        "version": os.getenv("APP_VERSION", "dev"),
        "contact": {
            "name": "Platform Engineering",
        },
    },
    "basePath": "/",
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "API key for authentication. Required when API_KEY env var is set. "
            "If API_KEY is not configured, authentication is disabled.",
        }
    },
    "security": [{"ApiKeyAuth": []}],
    "tags": [
        {
            "name": "Health",
            "description": "Health and status endpoints",
        },
        {
            "name": "System",
            "description": "System information endpoints",
        },
        {
            "name": "Load Testing",
            "description": "Synthetic load generation endpoints",
        },
        {
            "name": "CPU Load",
            "description": "Non-blocking CPU load workers distributed across cores",
        },
    ],
}


def init_swagger(app):
    """Initialize Swagger documentation for the app.

    Args:
        app: Flask application instance

    Returns:
        Swagger instance
    """
    app.config["SWAGGER"] = SWAGGER_CONFIG
    return Swagger(app, template=SWAGGER_TEMPLATE)
