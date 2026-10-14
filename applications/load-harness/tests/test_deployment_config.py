"""Infrastructure profiles do not select the metrics or authentication mode,
and the runtime image carries no test tooling but shares its base with tests."""

import re
from pathlib import Path

import pytest

from load_harness.app import create_app
from load_harness.services import (
    create_metrics_provider,
    KubernetesMetricsProvider,
    LocalMetricsProvider,
)


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
def test_explicit_kubernetes_metrics_work_in_every_environment(monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("METRICS_BACKEND", "kubernetes")
    assert isinstance(create_metrics_provider(), KubernetesMetricsProvider)


def test_explicit_process_metrics(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("METRICS_BACKEND", "local")
    assert isinstance(create_metrics_provider(), LocalMetricsProvider)


def test_unknown_metrics_backend_fails(monkeypatch):
    monkeypatch.setenv("METRICS_BACKEND", "aws")
    with pytest.raises(ValueError, match="METRICS_BACKEND"):
        create_metrics_provider()


def test_http_cookie_setting_does_not_disable_authentication(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    app = create_app({"API_KEY": "fixture-key"})
    assert app.config["SESSION_COOKIE_SECURE"] is False
    with app.test_client() as client:
        assert client.get("/version").status_code == 401
        assert client.get("/version", headers={"X-API-Key": "fixture-key"}).status_code == 200


def test_unknown_cookie_setting_fails(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "False")
    with pytest.raises(ValueError, match="SESSION_COOKIE_SECURE"):
        create_app()


@pytest.mark.parametrize(("scheme", "secure"), [("http", False), ("https", True)])
def test_public_scheme_decides_secure_cookies_in_a_cluster(monkeypatch, scheme, secure):
    monkeypatch.setenv("ENVIRONMENT", "kind")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("PUBLIC_SCHEME", scheme)
    assert create_app({"API_KEY": "fixture-key"}).config["SESSION_COOKIE_SECURE"] is secure


def test_runtime_requirements_exclude_test_tooling():
    """requirements.txt is what the image installs; pytest belongs in requirements-dev.txt."""
    runtime = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    names = {line.split("==")[0].strip().lower() for line in runtime.splitlines() if line.strip()}
    assert "pytest" not in names
    assert "flask" in names  # parsed the real file


def test_runtime_requirements_pin_every_package():
    """The image installs with --no-deps, so each line must be an exact pin."""
    runtime = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    pins = [line.split("#")[0].strip() for line in runtime.splitlines()]
    pins = [pin for pin in pins if pin]
    loose = [pin for pin in pins if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*==[^=<>~!,\s]+", pin)]
    assert loose == []
    assert any(pin.startswith("werkzeug==") for pin in pins)  # transitives included


def _from_lines(dockerfile):
    text = (Path(__file__).resolve().parents[1] / dockerfile).read_text()
    return [line.split()[1] for line in text.splitlines() if line.startswith("FROM ")]


def test_test_image_uses_the_production_base_digest():
    """Dockerfile.test must run tests on the exact base the image ships."""
    runtime_base = _from_lines("Dockerfile")[-1]
    assert "@sha256:" in runtime_base
    assert _from_lines("Dockerfile.test") == [runtime_base]
