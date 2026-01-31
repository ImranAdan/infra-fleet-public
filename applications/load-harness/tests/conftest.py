"""Shared pytest fixtures for load-harness tests.

This module provides common fixtures for testing the load-harness application.
All fixtures that are used across multiple test files should be defined here.
"""

import pytest
from prometheus_client import REGISTRY

from load_harness.app import create_app


def _clear_prometheus_registry():
    """Clear all Prometheus collectors to avoid duplicates between tests.

    Prometheus uses a global registry, so collectors registered in one test
    persist to the next. This helper ensures test isolation.
    """
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except ValueError:
            # Collector was already unregistered
            pass


@pytest.fixture(autouse=True)
def clean_prometheus():
    """Automatically clean Prometheus registry before and after each test.

    This fixture runs automatically for every test to ensure clean state.
    """
    _clear_prometheus_registry()
    yield
    _clear_prometheus_registry()


@pytest.fixture
def app():
    """Create Flask application for testing with auth disabled.

    Returns:
        Flask app configured for testing with authentication disabled.
        Debug mode enabled to simulate development environment (disables HSTS).
    """
    test_app = create_app({"API_KEY": None})
    test_app.config["TESTING"] = True
    test_app.debug = True
    return test_app


@pytest.fixture
def client(app):
    """Create test client with auth disabled.

    Use this fixture for tests that don't require authentication.
    """
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def app_with_auth():
    """Create Flask application with authentication enabled.

    Returns:
        Flask app configured for testing with a known API key.
        Debug mode enabled to simulate development environment (disables HSTS).
    """
    test_app = create_app({"API_KEY": "test-api-key-12345"})
    test_app.config["TESTING"] = True
    test_app.debug = True
    return test_app


@pytest.fixture
def client_with_auth(app_with_auth):
    """Create test client with authentication enabled.

    Use this fixture for testing authentication-related functionality.
    The expected API key is 'test-api-key-12345'.
    """
    with app_with_auth.test_client() as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    """Return headers with valid API key for authenticated requests."""
    return {"X-API-Key": "test-api-key-12345"}


@pytest.fixture
def app_production():
    """Create Flask application configured for production mode.

    This fixture is useful for testing HSTS headers and other
    production-only security features.
    """
    test_app = create_app({"API_KEY": None})
    test_app.config["TESTING"] = True
    test_app.debug = False  # Enable production security headers
    return test_app


@pytest.fixture
def client_production(app_production):
    """Create test client in production mode.

    Use this fixture for testing production-only security features
    like HSTS headers.
    """
    with app_production.test_client() as test_client:
        yield test_client
