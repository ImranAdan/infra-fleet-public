"""Tests for HTTP security headers.

These tests verify that security headers are correctly set on responses.
Headers tested address common web vulnerabilities identified by security
scanners (e.g., OWASP ZAP).
"""

import pytest


class TestSecurityHeaders:
    """Test suite for security header middleware."""

    def test_x_content_type_options(self, client):
        """Verify X-Content-Type-Options is set to prevent MIME sniffing."""
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        """Verify X-Frame-Options is set to prevent clickjacking."""
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        """Verify X-XSS-Protection is set for legacy browser XSS protection."""
        response = client.get("/health")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

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
        assert "cdn.tailwindcss.com" in csp
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
