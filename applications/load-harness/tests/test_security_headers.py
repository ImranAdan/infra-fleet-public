"""Tests for HTTP security headers.

These tests verify that security headers are correctly set on responses.
Headers tested address common web vulnerabilities identified by security
scanners (e.g., OWASP ZAP).
"""

import json
from html.parser import HTMLParser

import pytest


class TestSecurityHeaders:
    """Test suite for security header middleware."""

    @pytest.mark.parametrize("header,value", [
        ("X-Content-Type-Options", "nosniff"),        # MIME sniffing
        ("X-Frame-Options", "DENY"),                  # clickjacking
        ("X-XSS-Protection", "1; mode=block"),        # legacy browser XSS filter
    ])
    def test_fixed_value_headers(self, client, header, value):
        """Each header that must carry one exact value."""
        assert client.get("/health").headers.get(header) == value

    def test_content_security_policy_present(self, client):
        """Verify Content-Security-Policy header is present."""
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy")
        assert csp is not None
        assert "default-src" in csp

    def test_csp_includes_required_directives(self, client):
        """Verify CSP includes all required security directives."""
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy")

        # Required directives for security
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp  # Clickjacking protection
        assert "base-uri 'self'" in csp  # Base tag hijacking protection
        assert "form-action 'self'" in csp  # Form submission protection

    def test_csp_whitelists_cdn_sources(self, client):
        """Verify CSP whitelists required CDN sources for dependencies."""
        response = client.get("/health")
        csp = response.headers.get("Content-Security-Policy")

        # CDN dependencies
        assert "unpkg.com" in csp
        assert "cdn.jsdelivr.net" in csp

    def test_permissions_policy(self, client):
        """Verify Permissions-Policy disables unused browser features."""
        response = client.get("/health")
        permissions = response.headers.get("Permissions-Policy")

        assert permissions is not None
        # Verify dangerous features are disabled
        assert "geolocation=()" in permissions
        assert "camera=()" in permissions
        assert "microphone=()" in permissions

    def test_cross_origin_opener_policy(self, client):
        """Verify Cross-Origin-Opener-Policy is set for Spectre mitigation."""
        response = client.get("/health")
        coop = response.headers.get("Cross-Origin-Opener-Policy")
        assert coop == "same-origin"

    def test_cross_origin_resource_policy(self, client):
        """Verify Cross-Origin-Resource-Policy prevents cross-origin embedding."""
        response = client.get("/health")
        corp = response.headers.get("Cross-Origin-Resource-Policy")
        assert corp == "same-origin"

    def test_referrer_policy(self, client):
        """Verify Referrer-Policy limits referrer information leakage."""
        response = client.get("/health")
        referrer = response.headers.get("Referrer-Policy")
        assert referrer == "strict-origin-when-cross-origin"

    def test_cache_control_default(self, client):
        """Verify Cache-Control prevents caching of sensitive responses."""
        response = client.get("/health")
        cache = response.headers.get("Cache-Control")

        # API responses should not be cached by default
        assert cache is not None
        assert "no-store" in cache


class TestHSTSHeader:
    """Test suite for HSTS (HTTP Strict Transport Security) header.

    HSTS is only enabled in production mode (debug=False) to avoid
    issues during local development.
    """

    def test_hsts_not_set_in_debug_mode(self, client):
        """Verify HSTS is NOT set when running in debug/development mode."""
        response = client.get("/health")
        hsts = response.headers.get("Strict-Transport-Security")
        # In testing/debug mode, HSTS should not be set
        assert hsts is None

    def test_hsts_set_in_production_mode(self, client_production):
        """Verify HSTS IS set when running in production mode."""
        response = client_production.get("/health")
        hsts = response.headers.get("Strict-Transport-Security")

        assert hsts is not None
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts


class TestSecurityHeadersOnDifferentEndpoints:
    """Verify security headers are applied to all endpoints."""

    @pytest.mark.parametrize("endpoint", [
        "/",
        "/health",
        "/ready",
        "/version",
        "/system/info",
    ])
    def test_headers_on_api_endpoints(self, client, endpoint):
        """Verify security headers are set on various API endpoints."""
        response = client.get(endpoint)

        # Core security headers should be present on all responses
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Content-Security-Policy") is not None

    def test_headers_on_404_response(self, client):
        """Verify security headers are set even on 404 error responses."""
        response = client.get("/nonexistent-endpoint-12345")

        # Security headers should be present even on error responses
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_headers_on_post_request(self, client):
        """Verify security headers are set on POST responses."""
        response = client.post(
            "/load/cpu",
            json={"cores": 1, "duration_seconds": 5, "intensity": 1}
        )

        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"


def _script_src(client):
    csp = client.get("/health").headers["Content-Security-Policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    return directives["script-src"].split()


def test_script_src_forbids_inline_scripts(client):
    """No inline script may run: no 'unsafe-inline', no Tailwind Play CDN."""
    assert _script_src(client) == ["'self'", "https://unpkg.com", "https://cdn.jsdelivr.net"]


class _ScriptAudit(HTMLParser):
    """Collect what a script-src without 'unsafe-inline' would block or need."""

    def __init__(self):
        super().__init__()
        self.inline, self.handlers, self.local, self.styles = [], [], [], []
        self.htmx_config = None
        self._open_inline = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.handlers += [(tag, k) for k in attrs if k.startswith("on")]
        self.handlers += [(tag, k) for k, v in attrs.items() if v and v.lstrip().startswith("javascript:")]
        for key in ("src", "href"):
            if (attrs.get(key) or "").startswith("/static/"):
                self.local.append(attrs[key])
        self._open_inline = tag == "script" and "src" not in attrs
        if "style" in attrs or tag == "style":
            self.styles.append((tag, attrs.get("style")))
        if tag == "meta" and attrs.get("name") == "htmx-config":
            self.htmx_config = attrs.get("content")

    def handle_data(self, data):
        if self._open_inline and data.strip():
            self.inline.append(data.strip()[:60])

    def handle_endtag(self, tag):
        if tag == "script":
            self._open_inline = False


def _audit(client, path, expected_status=200):
    response = client.get(path)
    assert response.status_code == expected_status, path
    audit = _ScriptAudit()
    audit.feed(response.get_data(as_text=True))
    return audit


@pytest.mark.parametrize("path", ["/ui/", "/ui/partials/active-jobs", "/ui/partials/live-metrics"])
def test_dashboard_pages_have_no_inline_script(client, path):
    audit = _audit(client, path)
    assert audit.inline == []
    assert audit.handlers == []
    assert audit.styles == []


def test_login_page_has_no_inline_script(client_with_auth):
    audit = _audit(client_with_auth, "/ui/login")
    assert audit.inline == []
    assert audit.handlers == []
    assert audit.styles == []


def test_login_page_assets_load_before_login(client_with_auth):
    """The login page is public, so its stylesheet and scripts must be too."""
    login = set(_audit(client_with_auth, "/ui/login").local)
    assert login == {"/static/css/app.css", "/static/js/theme-init.js", "/static/js/theme.js"}
    for asset in login:
        assert client_with_auth.get(asset).status_code == 200, asset


def test_dashboard_assets_load(client):
    dashboard = set(_audit(client, "/ui/").local)
    assert dashboard == {
        "/static/css/app.css", "/static/js/theme-init.js",
        "/static/js/theme.js", "/static/js/dashboard.js",
    }
    for asset in dashboard:
        assert client.get(asset).status_code == 200, asset


def test_built_css_includes_custom_theme_and_dark_mode(client):
    """app.css came from tailwind.config.js: custom primary colours, class dark mode."""
    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert ".text-primary-600{" in css
    assert ".dark\\:bg-gray-900:is(.dark *){" in css


def _style_src(client):
    csp = client.get("/health").headers["Content-Security-Policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    return directives["style-src"].split()


def test_style_src_forbids_inline_styles(client):
    assert _style_src(client) == ["'self'"]


def test_htmx_does_not_inject_its_stylesheet(client):
    """HTMX adds a <style> element unless told not to; app.css carries its rules."""
    config = _audit(client, "/ui/").htmx_config
    assert config is not None and json.loads(config) == {"includeIndicatorStyles": False}


def _render(app, template, **context):
    from flask import render_template

    with app.test_request_context():
        audit = _ScriptAudit()
        html = render_template(template, **context)
        audit.feed(html)
        return html, audit


def test_cluster_metric_bars_use_width_classes(app):
    """Bars render widths as classes: no inline style, clamped and rounded."""
    html, audit = _render(
        app,
        "partials/live_metrics.html",
        is_local=False,
        cpu_usage=42.4,
        cpu_usage_max=87.6,
        memory_usage=130,
        memory_usage_max=None,
    )
    assert audit.styles == []
    for width in ("w-pct-42", "w-pct-88", "w-pct-100"):
        assert width in html, width

    html, audit = _render(
        app,
        "partials/pod_metrics.html",
        is_local=False,
        pods=[{"name": "p", "short_name": "p", "cpu_percent": 55.5, "memory_percent": None, "status": "Running"}],
    )
    assert audit.styles == []
    assert "w-pct-56" in html and "w-pct-0" in html


def test_built_css_carries_widths_and_indicator(client):
    css = client.get("/static/css/app.css").get_data(as_text=True)
    assert ".w-pct-0{width:0}" in css
    assert ".w-pct-42{width:42%}" in css
    assert ".w-pct-100{width:100%}" in css
    assert ".htmx-request .htmx-indicator,.htmx-request.htmx-indicator{display:inline-block}" in css
