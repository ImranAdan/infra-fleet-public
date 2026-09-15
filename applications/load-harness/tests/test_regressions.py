"""Regression tests for the review findings.

Each test here fails if one of the fixed defects comes back. They are grouped
by the behaviour they protect, not by the module they touch.
"""

import time

import pytest
from unittest.mock import MagicMock, patch

from load_harness.app import create_app
from load_harness.constants import LOGIN_LOCKOUT_SECONDS
from load_harness.dashboard import routes as dashboard_routes
from load_harness.load_harness_service import (
    _get_memory_limit_mb,
    _new_job_id,
)
from load_harness.services.job_manager import JobManager
from load_harness.services.memory_budget import MemoryBudget


def _stop_jobs(client):
    """Reap any worker processes a test started, so none outlive the session."""
    client.application.extensions["load_harness"].job_manager.stop_all_jobs()


# =============================================================================
# The dashboard must not call itself over HTTP
# =============================================================================


class TestDashboardCallsInProcess:
    """The self-HTTP hop deadlocked the gunicorn worker pool.

    Two concurrent dashboard actions occupied both sync workers, each waiting
    on an inner loopback request that no worker was left to serve, and /health
    went unanswered until the liveness probe restarted the pod.
    """

    def test_cpu_partial_makes_no_outbound_request(self, client):
        """Starting CPU load from the dashboard issues no HTTP request."""
        with patch.object(dashboard_routes.requests, "post") as post, \
             patch.object(dashboard_routes.requests, "get") as get:
            response = client.post(
                "/ui/partials/cpu-result",
                data={"cores": 1, "duration_seconds": 10, "intensity": 1},
            )

        assert response.status_code == 200
        assert b"CPU Load" in response.data
        post.assert_not_called()
        get.assert_not_called()

        _stop_jobs(client)

    def test_memory_partial_makes_no_outbound_request(self, client):
        """Starting memory load from the dashboard issues no HTTP request."""
        with patch.object(dashboard_routes.requests, "post") as post:
            response = client.post(
                "/ui/partials/memory-result",
                data={"size_mb": 1, "duration_seconds": 5},
            )

        assert response.status_code == 200
        post.assert_not_called()

        _stop_jobs(client)

    def test_system_info_partial_makes_no_outbound_request(self, client):
        """The dashboard reads system info in-process."""
        with patch.object(dashboard_routes.requests, "get") as get:
            response = client.get("/ui/api/system-info")

        assert response.status_code == 200
        assert "cpu_cores" in response.get_json()
        get.assert_not_called()

    def test_local_cluster_test_makes_no_outbound_request(self, client):
        """With no cluster to fan out to, the work runs here rather than over loopback."""
        with patch.object(dashboard_routes.requests, "post") as post:
            response = client.post(
                "/ui/partials/cluster-result",
                data={"concurrency": 4, "iterations": 1000},
            )

        assert response.status_code == 200
        post.assert_not_called()

    def test_cluster_url_is_none_when_local(self):
        """Local mode has no peer service URL, so nothing points at 127.0.0.1."""
        with patch.dict("os.environ", {"ENVIRONMENT": "local"}):
            assert dashboard_routes._get_k8s_service_url() is None

    def test_cluster_url_is_the_service_when_deployed(self):
        """In-cluster the fan-out still goes through the Service load balancer."""
        with patch.dict("os.environ", {"ENVIRONMENT": "staging"}):
            url = dashboard_routes._get_k8s_service_url()
        assert url == "http://load-harness.applications.svc.cluster.local:5000"


# =============================================================================
# Memory ceiling must respect the container limit
# =============================================================================


class TestMemoryCeiling:
    """A documented in-range size_mb used to exceed the cgroup limit."""

    def test_ceiling_derived_from_cgroup_limit(self):
        """A 1Gi cgroup yields a ceiling below 1024MB, not the static 2048."""
        one_gib = str(1024 * 1024 * 1024)

        def fake_open(path, *args, **kwargs):
            if path == "/sys/fs/cgroup/memory.max":
                return MagicMock(
                    __enter__=lambda s: MagicMock(read=lambda: one_gib),
                    __exit__=lambda *a: None,
                )
            raise FileNotFoundError(path)

        with patch("builtins.open", side_effect=fake_open):
            limit = _get_memory_limit_mb()

        assert limit < 1024, "ceiling must stay under the 1Gi container limit"
        assert limit > 0

    def test_unlimited_cgroup_falls_back_to_constant(self):
        """With no cgroup limit the static maximum still applies."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            assert _get_memory_limit_mb() == 2048

    def test_request_above_ceiling_is_rejected(self, app):
        """A size_mb over the derived ceiling is a 400, not an OOM kill."""
        service = app.extensions["load_harness"]
        service.memory_limit_mb = 100

        body, status = service.start_memory_load(size_mb=500, duration_seconds=5)

        assert status == 400
        assert "100" in body["error"]

    def test_sync_endpoint_uses_the_same_ceiling(self, client, app):
        """The blocking endpoint allocates in the web worker, so it must not be looser."""
        app.extensions["load_harness"].memory_limit_mb = 100

        response = client.post("/load/memory/sync", json={"size_mb": 500})

        assert response.status_code == 400

    def test_memory_budget_is_shared_between_service_processes(self, tmp_path):
        """Two Gunicorn workers cannot each reserve the full pod budget."""
        first_worker = MemoryBudget(100, str(tmp_path))
        second_worker = MemoryBudget(100, str(tmp_path))

        first_reservation = first_worker.reserve(60)
        assert first_reservation
        assert second_worker.reserve(50) is None

        first_worker.release(first_reservation)
        second_reservation = second_worker.reserve(50)
        assert second_reservation
        second_worker.release(second_reservation)

    def test_service_rejects_memory_beyond_remaining_budget(self, tmp_path, app):
        """The endpoint participates in the shared budget before spawning."""
        service = app.extensions["load_harness"]
        service.memory_limit_mb = 100
        service.memory_budget = MemoryBudget(100, str(tmp_path))
        reservation = service.memory_budget.reserve(60)

        body, status = service.start_memory_load(size_mb=50, duration_seconds=5)

        assert status == 409
        assert "capacity remaining" in body["error"]
        service.memory_budget.release(reservation)

    def test_dead_memory_worker_reservation_is_reclaimed(self, tmp_path):
        """A crashed worker cannot leave the pod budget permanently reserved."""
        first_worker = MemoryBudget(100, str(tmp_path))
        reservation = first_worker.reserve(100)
        first_worker.activate(reservation, 2_000_000_000)

        second_worker = MemoryBudget(100, str(tmp_path))
        replacement = second_worker.reserve(100)
        assert replacement
        second_worker.release(replacement)


# =============================================================================
# Job identity
# =============================================================================


class TestJobIds:
    """Millisecond timestamps collided and silently orphaned worker processes."""

    def test_ids_are_unique_within_the_same_millisecond(self):
        """Freeze the clock; the IDs must still differ."""
        with patch("load_harness.load_harness_service.time.time", return_value=1000.0):
            ids = {_new_job_id("job_") for _ in range(500)}

        assert len(ids) == 500

    def test_id_keeps_its_prefix(self):
        """Status filtering and log grepping rely on the prefix."""
        assert _new_job_id("mem_").startswith("mem_")

    def test_dashboard_exposes_the_complete_job_id_to_javascript(self, client, app):
        """The browser must retain the suffix that makes simultaneous IDs unique."""
        service = app.extensions["load_harness"]
        body = {
            "status": "started",
            "job_id": "job_1000000_deadbeef",
            "cores": 1,
            "duration_seconds": 10,
            "intensity": 1,
        }
        with patch.object(service, "start_cpu_load", return_value=(body, 200)):
            response = client.post(
                "/ui/partials/cpu-result",
                data={"cores": 1, "duration_seconds": 10, "intensity": 1},
            )

        assert b'data-job-id="job_1000000_deadbeef"' in response.data
        javascript = client.get("/static/js/dashboard.js").data
        assert b"job_id: result.dataset.jobId" in javascript


# =============================================================================
# JobManager locking and retention
# =============================================================================


class TestJobManagerLifecycle:
    """Reaping under the lock blocked every status poll for the wait duration."""

    def test_stop_job_reaps_outside_the_lock(self):
        """The lock must be free while a worker process is being joined."""
        manager = JobManager()
        observed = {}

        process = MagicMock()
        process.is_alive.return_value = False
        # acquire() is non-blocking here: True means the lock was free.
        process.join.side_effect = lambda **kw: observed.update(
            free=manager._lock.acquire(blocking=False)
        )

        manager.register_job("job-1", "cpu", {}, [process], MagicMock())
        assert manager.stop_job("job-1")

        if observed.get("free"):
            manager._lock.release()
        assert observed["free"], "lock was held while joining a worker process"

    def test_stopped_job_is_json_serializable(self):
        """Detaching the handles also keeps the job dict serializable."""
        manager = JobManager()
        manager.register_job("job-1", "cpu", {}, [], MagicMock())
        manager.stop_job("job-1")

        job = manager.get_job("job-1")
        assert "processes" not in job
        assert "stop_event" not in job

    @patch("load_harness.services.job_manager.time.sleep", return_value=None)
    def test_cleanup_evicts_old_finished_jobs(self, _mock_sleep):
        """Finished jobs must not accumulate for the life of the process."""
        manager = JobManager()
        manager.register_job("old-job", "cpu", {}, [], MagicMock())
        manager.stop_job("old-job")
        # Backdate the job past the retention window.
        manager._jobs["old-job"]["stopped_at"] = "2020-01-01T00:00:00+00:00"

        manager.register_job("new-job", "cpu", {}, [], MagicMock())
        manager._cleanup_job("new-job", 0, None)

        assert manager.get_job("old-job") is None
        assert manager.get_job("new-job") is not None


# =============================================================================
# Authentication
# =============================================================================


class TestAuthentication:
    """Auth must fail closed, and a malformed key must not 500."""

    def test_refuses_to_start_without_api_key_outside_local(self):
        """A missing Secret must crash-loop visibly, not serve openly."""
        with patch.dict("os.environ", {"ENVIRONMENT": "staging"}, clear=False):
            with pytest.raises(RuntimeError, match="API_KEY must be set"):
                create_app({"API_KEY": None})

    def test_starts_without_api_key_locally(self):
        """Local development keeps the open default."""
        with patch.dict("os.environ", {"ENVIRONMENT": "local"}, clear=False):
            assert create_app({"API_KEY": None}) is not None

    def test_non_ascii_api_key_is_unauthorized_not_an_error(self, client_with_auth):
        """compare_digest rejects non-ASCII str, which used to raise a 500."""
        response = client_with_auth.get(
            "/load/cpu/status", headers={"X-API-Key": "ünïcödé-key"}
        )
        assert response.status_code == 401

    def test_login_locks_out_after_repeated_failures(self, client_with_auth):
        """The login form guards one shared key, so cap the guess rate."""
        dashboard_routes._login_failures.clear()

        for _ in range(5):
            response = client_with_auth.post("/ui/login", data={"api_key": "wrong"})
            assert response.status_code == 200

        response = client_with_auth.post("/ui/login", data={"api_key": "wrong"})
        assert response.status_code == 429

        dashboard_routes._login_failures.clear()

    def test_successful_login_clears_the_counter(self, client_with_auth):
        """A user who mistypes once is not penalised after they get in."""
        dashboard_routes._login_failures.clear()

        client_with_auth.post("/ui/login", data={"api_key": "wrong"})
        client_with_auth.post("/ui/login", data={"api_key": "test-api-key-12345"})

        assert not dashboard_routes._login_failures

        dashboard_routes._login_failures.clear()

    def test_login_cache_drops_addresses_that_never_return(self):
        """Failures from many one-off addresses must not grow the map forever."""
        dashboard_routes._login_failures.clear()

        # A burst of distinct addresses, all older than the lockout window.
        stale = time.monotonic() - (LOGIN_LOCKOUT_SECONDS + 1)
        for i in range(100):
            dashboard_routes._login_failures[f"10.0.0.{i}"] = [stale]

        dashboard_routes._record_login_failure("10.0.1.1")

        assert list(dashboard_routes._login_failures) == ["10.0.1.1"]

        dashboard_routes._login_failures.clear()

    def test_login_failure_cache_is_bounded_during_a_burst(self):
        """Recent one-off addresses cannot grow the process cache forever."""
        dashboard_routes._login_failures.clear()

        with patch.object(dashboard_routes, "LOGIN_FAILURE_CACHE_MAX_CLIENTS", 3):
            for index in range(10):
                dashboard_routes._record_login_failure(f"192.0.2.{index}")

        assert len(dashboard_routes._login_failures) == 3
        dashboard_routes._login_failures.clear()
