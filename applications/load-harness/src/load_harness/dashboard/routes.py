# src/load_harness/dashboard/routes.py
"""Dashboard routes for LoadHarness web UI."""

import os
import secrets
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import (
    Blueprint,
    render_template,
    request,
    current_app,
    jsonify,
    redirect,
    url_for,
    session,
)

from load_harness.constants import (
    API_REQUEST_TIMEOUT,
    CLUSTER_MAX_CONCURRENCY,
    CLUSTER_MIN_CONCURRENCY,
    CLUSTER_REQUEST_TIMEOUT,
    CPU_WORK_MAX_ITERATIONS,
    CPU_WORK_MIN_ITERATIONS,
)
from load_harness.services import (
    PrometheusClient,
    create_metrics_provider,
)

dashboard = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/ui",
    template_folder="../templates",
)


# ---- Authentication Routes ----


@dashboard.route("/login", methods=["GET", "POST"])
def login():
    """Handle login page and authentication."""
    error = None

    # If already authenticated, redirect to dashboard
    if session.get("authenticated"):
        return redirect(url_for("dashboard.index"))

    # If auth is disabled (no API_KEY), redirect to dashboard
    if not current_app.config.get("API_KEY"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        provided_key = request.form.get("api_key", "").strip()
        expected_key = current_app.config.get("API_KEY")

        # Use constant-time comparison to prevent timing attacks
        if provided_key and expected_key and secrets.compare_digest(provided_key, expected_key):
            session["authenticated"] = True
            session.permanent = True  # Use permanent session
            current_app.logger.info("User authenticated from %s", request.remote_addr)
            return redirect(url_for("dashboard.index"))
        else:
            error = "Invalid API key. Please try again."
            current_app.logger.warning(
                "Failed login attempt from %s", request.remote_addr
            )

    return render_template("login.html", error=error)


@dashboard.route("/logout")
def logout():
    """Clear session and redirect to login.

    Properly invalidates the session by:
    1. Removing the authenticated flag
    2. Clearing all session data
    3. Marking session as modified to ensure cookie update
    """
    session.pop("authenticated", None)
    session.clear()
    session.modified = True
    return redirect(url_for("dashboard.login"))


def _get_api_base_url() -> str:
    """Get the base URL for internal API calls.

    Uses the PORT environment variable to call the local Flask server.
    This works both in Kubernetes (PORT=5000) and local development.
    """
    port = os.environ.get("PORT", "5000")
    return f"http://127.0.0.1:{port}"


def _get_auth_headers() -> dict:
    """Get authentication headers for internal API calls.

    Returns headers dict with X-API-Key if authentication is enabled.
    """
    api_key = current_app.config.get("API_KEY")
    if api_key:
        return {"X-API-Key": api_key}
    return {}


# Module-level metrics provider (lazy initialized)
_metrics_provider = None


def _get_metrics_provider():
    """Get or create the metrics provider singleton."""
    global _metrics_provider
    if _metrics_provider is None:
        _metrics_provider = create_metrics_provider()
    return _metrics_provider


@dashboard.route("/")
def index():
    """Render main dashboard page."""
    # Fetch system info for CPU cores
    try:
        response = requests.get(
            f"{_get_api_base_url()}/system/info",
            headers=_get_auth_headers(),
            timeout=5,
        )
        if response.status_code == 200:
            system_info = response.json()
        else:
            system_info = {"cpu_cores": 1}
    except Exception:
        system_info = {"cpu_cores": 1}

    # Check if running locally
    is_local = _is_local_environment()

    return render_template("dashboard.html", system_info=system_info, is_local=is_local)


@dashboard.route("/api/system-info")
def system_info():
    """Proxy system info from backend API."""
    try:
        response = requests.get(
            f"{_get_api_base_url()}/system/info",
            headers=_get_auth_headers(),
            timeout=5,
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({"error": str(e), "cpu_cores": 1}), 500


@dashboard.route("/partials/cpu-result", methods=["POST"])
def cpu_result():
    """Start CPU load test and return result partial."""
    try:
        cores = int(request.form.get("cores", 1))
        duration_seconds = int(request.form.get("duration_seconds", 60))
        intensity = int(request.form.get("intensity", 5))

        response = requests.post(
            f"{_get_api_base_url()}/load/cpu",
            json={
                "cores": cores,
                "duration_seconds": duration_seconds,
                "intensity": intensity,
            },
            headers=_get_auth_headers(),
            timeout=10,
        )

        if response.status_code == 200:
            return render_template(
                "partials/result.html",
                status="success",
                test_type="CPU Load",
                data=response.json(),
                is_cpu_load=True,
            )
        else:
            return render_template(
                "partials/result.html",
                status="error",
                message=response.json().get("error", "Unknown error"),
            )
    except requests.exceptions.Timeout:
        return render_template(
            "partials/result.html",
            status="error",
            message="Request timed out.",
        )
    except requests.exceptions.ConnectionError:
        return render_template(
            "partials/result.html",
            status="error",
            message="Could not connect to API. Is the server running?",
        )
    except Exception as e:
        current_app.logger.error("CPU load test error: %s", e)
        return render_template(
            "partials/result.html",
            status="error",
            message=str(e),
        )


@dashboard.route("/partials/memory-result", methods=["POST"])
def memory_result():
    """Start Memory load test and return result partial (non-blocking)."""
    try:
        size_mb = int(request.form.get("size_mb", 100))
        duration_seconds = int(request.form.get("duration_seconds", 30))

        response = requests.post(
            f"{_get_api_base_url()}/load/memory",
            json={"size_mb": size_mb, "duration_seconds": duration_seconds},
            headers=_get_auth_headers(),
            timeout=10,  # Non-blocking, returns immediately
        )

        if response.status_code == 200:
            return render_template(
                "partials/result.html",
                status="success",
                test_type="Memory Load",
                data=response.json(),
                is_memory_load=True,
            )
        else:
            return render_template(
                "partials/result.html",
                status="error",
                message=response.json().get("error", "Unknown error"),
            )
    except requests.exceptions.Timeout:
        return render_template(
            "partials/result.html",
            status="error",
            message="Request timed out.",
        )
    except requests.exceptions.ConnectionError:
        return render_template(
            "partials/result.html",
            status="error",
            message="Could not connect to API. Is the server running?",
        )
    except Exception as e:
        current_app.logger.error("Memory load test error: %s", e)
        return render_template(
            "partials/result.html",
            status="error",
            message=str(e),
        )


def _is_local_environment() -> bool:
    """Check if running in local docker-compose environment."""
    return os.environ.get("ENVIRONMENT", "local") == "local"


@dashboard.route("/partials/live-metrics")
def live_metrics():
    """Return live metrics partial with data from Prometheus.

    Uses MetricsProvider abstraction to handle both local and cluster modes.
    """
    provider = _get_metrics_provider()
    metrics = provider.collect_metrics()

    return render_template(
        "partials/live_metrics.html",
        pod_count=metrics.pod_count,
        cpu_usage=round(metrics.cpu_usage, 1) if metrics.cpu_usage is not None else None,
        cpu_usage_max=round(metrics.cpu_usage_max, 1) if metrics.cpu_usage_max is not None else None,
        memory_usage=round(metrics.memory_usage, 1) if metrics.memory_usage is not None else None,
        memory_usage_max=round(metrics.memory_usage_max, 1) if metrics.memory_usage_max is not None else None,
        request_rate=round(metrics.request_rate, 2) if metrics.request_rate is not None else None,
        hpa_scaled=metrics.hpa_scaled,
        is_local=metrics.is_local,
    )


@dashboard.route("/partials/pod-metrics")
def pod_metrics():
    """Return per-pod CPU metrics for the Pod Monitor panel.

    Uses MetricsProvider abstraction to handle both local and cluster modes.
    """
    provider = _get_metrics_provider()
    pods = provider.collect_pod_metrics()

    # Convert PodMetrics dataclasses to dicts for template
    pod_list = [
        {
            "name": pod.name,
            "short_name": pod.short_name,
            "cpu_percent": pod.cpu_percent,
            "memory_percent": pod.memory_percent,
            "status": pod.status,
        }
        for pod in pods
    ]

    return render_template(
        "partials/pod_metrics.html",
        pods=pod_list,
        is_local=provider.is_local,
    )


def _get_k8s_service_url() -> str:
    """Get the Kubernetes Service URL for distributed load testing.

    In Kubernetes: Uses the in-cluster service URL on port 5000.
    Locally: Uses the local Flask server.

    Note: Port 5000 must be specified explicitly because Flagger manages the
    load-harness service and configures it with port 5000 (matching the container
    port) rather than the standard HTTP port 80.
    """
    env = os.environ.get("ENVIRONMENT", "local")
    if env == "local":
        return _get_api_base_url()
    # In-cluster service URL for load distribution across pods
    # Port 5000 required - Flagger configures the service with port 5000
    return "http://load-harness.applications.svc.cluster.local:5000"


def _send_work_request(
    service_url: str, iterations: int, request_id: int, headers: dict
) -> dict:
    """Send a single work request and return the result."""
    try:
        response = requests.post(
            f"{service_url}/load/cpu/work",
            json={"iterations": iterations},
            headers=headers,
            timeout=120,
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "request_id": request_id,
                "success": True,
                "pod_name": data.get("pod_name", "unknown"),
                "duration_ms": data.get("duration_ms", 0),
                "iterations": data.get("iterations", 0),
            }
        return {
            "request_id": request_id,
            "success": False,
            "error": f"HTTP {response.status_code}",
        }
    except Exception as e:
        return {
            "request_id": request_id,
            "success": False,
            "error": str(e),
        }


@dashboard.route("/partials/cluster-result", methods=["POST"])
def cluster_result():
    """Run distributed load test across the cluster."""
    try:
        concurrency = int(request.form.get("concurrency", 10))
        iterations = int(request.form.get("iterations", 500000))

        # Validate inputs using constants
        if concurrency < CLUSTER_MIN_CONCURRENCY or concurrency > CLUSTER_MAX_CONCURRENCY:
            return render_template(
                "partials/result.html",
                status="error",
                message=f"Concurrency must be between {CLUSTER_MIN_CONCURRENCY} and {CLUSTER_MAX_CONCURRENCY}",
            )

        if iterations < CPU_WORK_MIN_ITERATIONS or iterations > CPU_WORK_MAX_ITERATIONS:
            return render_template(
                "partials/result.html",
                status="error",
                message=f"Iterations must be between {CPU_WORK_MIN_ITERATIONS:,} and {CPU_WORK_MAX_ITERATIONS:,}",
            )

        service_url = _get_k8s_service_url()
        auth_headers = _get_auth_headers()

        # Send concurrent requests using ThreadPoolExecutor
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    _send_work_request, service_url, iterations, i, auth_headers
                ): i
                for i in range(concurrency)
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Aggregate results
        successful = [r for r in results if r.get("success")]
        failed = [r for r in results if not r.get("success")]

        # If all requests failed, show error with details
        if not successful:
            # Get the first error message for context
            first_error = failed[0].get("error", "Unknown error") if failed else "Unknown error"
            return render_template(
                "partials/result.html",
                status="error",
                message=f"All {concurrency} requests failed. First error: {first_error}",
            )

        # Count requests per pod
        pod_distribution = {}
        total_duration_ms = 0
        for r in successful:
            pod_name = r.get("pod_name", "unknown")
            pod_distribution[pod_name] = pod_distribution.get(pod_name, 0) + 1
            total_duration_ms += r.get("duration_ms", 0)

        avg_duration_ms = (
            total_duration_ms / len(successful) if successful else 0
        )

        return render_template(
            "partials/result.html",
            status="success",
            test_type="Cluster Load",
            is_cluster_load=True,
            data={
                "status": "completed",
                "total_requests": concurrency,
                "successful": len(successful),
                "failed": len(failed),
                "iterations_per_request": iterations,
                "avg_duration_ms": round(avg_duration_ms, 2),
                "pod_distribution": pod_distribution,
                "pods_used": len(pod_distribution),
            },
        )

    except Exception as e:
        current_app.logger.error("Cluster load test error: %s", e)
        return render_template(
            "partials/result.html",
            status="error",
            message=str(e),
        )


@dashboard.route("/partials/active-jobs")
def active_jobs():
    """Return active jobs partial with status from the API.

    Note: This endpoint is kept for backwards compatibility but the dashboard
    now uses client-side job tracking to avoid multi-pod polling issues.
    """
    try:
        response = requests.get(
            f"{_get_api_base_url()}/load/cpu/status",
            headers=_get_auth_headers(),
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            jobs = data.get("jobs", [])
            active_jobs_count = data.get("active_jobs", 0)
            return render_template(
                "partials/active_jobs.html",
                jobs=jobs,
                active_jobs_count=active_jobs_count,
            )
    except Exception as e:
        current_app.logger.warning("Failed to fetch jobs status: %s", e)

    return render_template(
        "partials/active_jobs.html",
        jobs=[],
        active_jobs_count=0,
    )
