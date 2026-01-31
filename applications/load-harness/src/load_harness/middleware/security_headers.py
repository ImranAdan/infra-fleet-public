"""HTTP security headers middleware.

Implements security headers to protect against common web vulnerabilities.
These headers address findings from ZAP baseline security scans.

CSP 'unsafe-inline' Rationale:
------------------------------
The current CSP includes 'unsafe-inline' for scripts and styles because:

1. **Tailwind CSS CDN** requires inline <script> for configuration
2. **Dark mode initialization** must run inline before body renders to prevent
   flash of incorrect theme (FOUC)
3. **Tailwind JIT mode** (CDN) generates inline styles at runtime

For production hardening, consider:
- Build Tailwind CSS at compile time (removes CDN dependency)
- Use nonce-based CSP for remaining inline scripts
- Move all inline scripts to external files (dashboard.js, theme.js done)

External scripts now live in static/js/ to reduce inline dependencies.
"""

# Content Security Policy configuration
# Whitelists script sources for CDN dependencies:
# - Tailwind CSS (cdn.tailwindcss.com) - requires 'unsafe-inline' for config
# - HTMX (unpkg.com)
# - Chart.js (cdn.jsdelivr.net)
#
# TODO: Remove 'unsafe-inline' by:
# 1. Building Tailwind at compile time instead of using CDN
# 2. Computing SHA-256 hashes for remaining inline scripts
# 3. Using nonce-based CSP (requires request-time nonce generation)
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


def init_security_headers(app):
    """Add security headers to all responses.

    Headers applied:
    - X-Content-Type-Options: Prevents MIME-type sniffing attacks
    - X-Frame-Options: Prevents clickjacking by blocking iframe embedding
    - X-XSS-Protection: Legacy XSS filter for older browsers
    - Strict-Transport-Security: Forces HTTPS connections (HSTS)
    - Content-Security-Policy: Controls allowed resource sources (XSS prevention)
    - Permissions-Policy: Disables unused browser features
    - Cross-Origin-Opener-Policy: Isolates browsing context (Spectre mitigation)
    - Cross-Origin-Resource-Policy: Prevents cross-origin resource embedding
    - Referrer-Policy: Controls referrer information leakage

    Args:
        app: Flask application instance
    """

    @app.after_request
    def add_security_headers(response):
        # =================================================================
        # Legacy Headers (for older browser compatibility)
        # =================================================================

        # Prevent browsers from MIME-sniffing the content-type
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent the page from being embedded in iframes (clickjacking protection)
        # Also covered by CSP frame-ancestors, but needed for older browsers
        response.headers["X-Frame-Options"] = "DENY"

        # Enable XSS filter in older browsers (modern browsers have this built-in)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # =================================================================
        # Modern Security Headers
        # =================================================================

        # Force HTTPS for 1 year, including subdomains
        # Only set when not in debug mode to avoid issues during local development
        if not app.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Content Security Policy - controls allowed resource sources
        # Prevents XSS by whitelisting script/style sources
        response.headers["Content-Security-Policy"] = CSP_POLICY

        # Permissions Policy - disables unused browser features
        # Reduces attack surface if XSS occurs
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
        )

        # Cross-Origin-Opener-Policy - isolates browsing context
        # Prevents other tabs from getting window.opener reference (Spectre mitigation)
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        # Cross-Origin-Resource-Policy - prevents cross-origin embedding
        # Blocks other sites from embedding our resources via <img>, <script>, etc.
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Referrer-Policy - controls referrer information sent to other origins
        # Sends origin only when navigating to different origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # =================================================================
        # Cache Control
        # =================================================================

        # Prevent caching of sensitive responses
        # API responses may contain session data, so don't cache by default
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store, max-age=0"

        return response

    app.logger.info("Security headers middleware enabled")
