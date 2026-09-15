# src/load_harness/dashboard/routes.py
"""Dashboard routes for LoadHarness web UI."""

import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from typing import Optional

import requests
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
    CLUSTER_MAX_CONCURRENCY,
    CLUSTER_MIN_CONCURRENCY,
    CLUSTER_REQUEST_TIMEOUT,
    CPU_WORK_MAX_ITERATIONS,
    CPU_WORK_MIN_ITERATIONS,
    LOGIN_LOCKOUT_SECONDS,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_FAILURE_CACHE_MAX_CLIENTS,
)
from load_harness.services import create_metrics_provider

dashboard = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/ui",
    template_folder="../templates",
)


# ---- Authentication Routes ----

# Failed login attempts per client address. The login form guards a single
# shared API key, so an unbounded guess rate is the whole attack.
#
# ponytail: per-process dict, so the real ceiling is LOGIN_MAX_ATTEMPTS x
# gunicorn workers x pods - measured at 10 attempts before lockout with the
# shipped 2-worker container, not 5. That is a bound, which is the point; it is
# not a precise one. Move it to the ingress or a shared store if an exact
# per-address limit matters.
_login_failures = {}
_login_lock = threading.Lock()


def _login_blocked(client: str) -> bool:
    """Report whether this client is currently locked out, pruning old attempts.

    Never inserts a key: a lookup that created an entry would let an attacker
    grow this dictionary one address at a time just by probing the login page.
    """
    cutoff = time.monotonic() - LOGIN_LOCKOUT_SECONDS
    with _login_lock:
        attempts = [t for t in _login_failures.get(client, ()) if t > cutoff]
        if attempts:
            _login_failures[client] = attempts
        else:
            _login_failures.pop(client, None)
        return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_login_failure(client: str) -> None:
    """Record a failed attempt, dropping every entry that has aged out.

    Prunes all clients, not just this one. _login_blocked only expires the
    address in front of it, so addresses that fail once and never return would
    otherwise sit here for the life of the process - and failures arriving from
    many addresses would grow the map without bound. Pruning costs one pass
    over a map that only failed logins can grow.
    """
    now = time.monotonic()
    cutoff = now - LOGIN_LOCKOUT_SECONDS
    with _login_lock:
        for address in [a for a, times in _login_failures.items() if times[-1] <= cutoff]:
            del _login_failures[address]
        if (
            client not in _login_failures
            and len(_login_failures) >= LOGIN_FAILURE_CACHE_MAX_CLIENTS
        ):
            oldest = min(
                _login_failures,
                key=lambda address: _login_failures[address][-1],
            )
            del _login_failures[oldest]
        _login_failures.setdefault(client, []).append(now)


def _clear_login_failures(client: str) -> None:
    """Forget a client's failures after a successful login."""
    with _login_lock:
        _login_failures.pop(client, None)


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
        client = request.remote_addr or "unknown"

        if _login_blocked(client):
            current_app.logger.warning("Login lockout in effect for %s", client)
            return render_template(
                "login.html",
                error=f"Too many failed attempts. Try again in {LOGIN_LOCKOUT_SECONDS} seconds.",
            ), 429

        provided_key = request.form.get("api_key", "").strip()
        expected_key = current_app.config.get("API_KEY")

        # Constant-time comparison to prevent timing attacks. Compare bytes:
        # compare_digest rejects str arguments holding non-ASCII characters.
        if provided_key and expected_key and secrets.compare_digest(
            provided_key.encode("utf-8"), expected_key.encode("utf-8")
        ):
            _clear_login_failures(client)
            session["authenticated"] = True
            session.permanent = True  # Use permanent session
            current_app.logger.info("User authenticated from %s", client)
            return redirect(url_for("dashboard.index"))
        else:
            _record_login_failure(client)
            error = "Invalid API key. Please try again."
            current_app.logger.warning("Failed login attempt from %s", client)

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


def _service():
    """Get the LoadHarnessService running in this process.

    The dashboard used to reach the API over HTTP against 127.0.0.1. With sync
    gunicorn workers that deadlocks: the outer request holds a worker while its
    own inner request waits for one, so two concurrent dashboard actions stall
    the pool and /health stops answering until the probe restarts the pod.
    Same process, so call it directly.
    """
    return current_app.extensions["load_harness"]


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
        system_info = _service().get_system_info()
    except Exception:
        system_info = {"cpu_cores": 1}

    # Check if running locally
    is_local = _is_local_environment()

    return render_template("dashboard.html", system_info=system_info, is_local=is_local)


@dashboard.route("/api/system-info")
def system_info():
    """Return system info for the dashboard."""
    try:
        return jsonify(_service().get_system_info()), 200
    except Exception as e:
        current_app.logger.error("System info error: %s", e)
        return jsonify({"error": str(e), "cpu_cores": 1}), 500


@dashboard.route("/partials/cpu-result", methods=["POST"])
def cpu_result():
    """Start CPU load test and return result partial."""
    try:
        cores = int(request.form.get("cores", 1))
        duration_seconds = int(request.form.get("duration_seconds", 60))
        intensity = int(request.form.get("intensity", 5))

        body, status = _service().start_cpu_load(cores, duration_seconds, intensity)

        if status == 200:
            return render_template(
                "partials/result.html",
                status="success",
                test_type="CPU Load",
                data=body,
                is_cpu_load=True,
            )
        return render_template(
            "partials/result.html",
            status="error",
            message=body.get("error", "Unknown error"),
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

        body, status = _service().start_memory_load(size_mb, duration_seconds)

        if status == 200:
            return render_template(
                "partials/result.html",
                status="success",
                test_type="Memory Load",
                data=body,
                is_memory_load=True,
            )
        return render_template(
            "partials/result.html",
            status="error",
            message=body.get("error", "Unknown error"),
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


def _get_k8s_service_url() -> Optional[str]:
    """Get the Kubernetes Service URL for distributed load testing.

    Returns None when running locally: there is no cluster to spread work
    across, so the work runs in this process rather than over a loopback
    request that would starve the worker pool.

    Note: Port 5000 must be specified explicitly because Flagger manages the
    load-harness service and configures it with port 5000 (matching the container
    port) rather than the standard HTTP port 80.
    """
    if os.environ.get("ENVIRONMENT", "local") == "local":
        return None
    # In-cluster service URL for load distribution across pods
    # Port 5000 required - Flagger configures the service with port 5000
    return "http://load-harness.applications.svc.cluster.local:5000"


def _send_work_request(
    service_url: str, iterations: int, request_id: int, headers: dict
) -> dict:
    """Send a single work request to a cluster peer and return the result.

    This is a genuine fan-out across pods via the Service load balancer, so it
    stays HTTP. Only ever called with a real cluster URL - see _run_work_local
    for the single-process case.
    """
    try:
        response = requests.post(
            f"{service_url}/load/cpu/work",
            json={"iterations": iterations},
            headers=headers,
            timeout=CLUSTER_REQUEST_TIMEOUT,
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


def _run_work_local(service, iterations: int, request_id: int) -> dict:
    """Run one unit of CPU work in this process, no HTTP hop."""
    try:
        body, status = service.run_cpu_work(iterations)
        if status == 200:
            return {
                "request_id": request_id,
                "success": True,
                "pod_name": body.get("pod_name", "unknown"),
                "duration_ms": body.get("duration_ms", 0),
                "iterations": body.get("iterations", 0),
            }
        return {
            "request_id": request_id,
            "success": False,
            "error": body.get("error", f"HTTP {status}"),
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

        if service_url:
            api_key = current_app.config.get("API_KEY")
            headers = {"X-API-Key": api_key} if api_key else {}
            run = partial(_send_work_request, service_url, iterations, headers=headers)
        else:
            run = partial(_run_work_local, _service(), iterations)

        # Send concurrent requests using ThreadPoolExecutor
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(run, i): i for i in range(concurrency)}
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
        data = _service().get_cpu_status()
        return render_template(
            "partials/active_jobs.html",
            jobs=data.get("jobs", []),
            active_jobs_count=data.get("active_jobs", 0),
        )
    except Exception as e:
        current_app.logger.warning("Failed to fetch jobs status: %s", e)

    return render_template(
        "partials/active_jobs.html",
        jobs=[],
        active_jobs_count=0,
    )
