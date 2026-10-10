"""HTTP security headers middleware.

Implements security headers to protect against common web vulnerabilities.
These headers address findings from ZAP baseline security scans.

CSP:
----
Scripts are external only: page scripts live in static/js/ and the CDN
libraries (HTMX on unpkg.com, Chart.js on cdn.jsdelivr.net) carry SRI hashes.
Tailwind is built ahead of time into static/css/app.css (`npm run build:css`),
so no inline script runs and script-src does not allow 'unsafe-inline'.

style-src still allows 'unsafe-inline': the metrics partials set widths with
style attributes and HTMX injects its indicator styles at runtime.
"""

# Content Security Policy configuration
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
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
