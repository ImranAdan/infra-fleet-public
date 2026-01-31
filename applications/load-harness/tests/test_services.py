"""Tests for the services module.

Tests PrometheusClient, MetricsProvider, and JobManager services.
"""

import time
import threading
from multiprocessing import Event, Process
from unittest.mock import MagicMock, patch, Mock

import pytest

from load_harness.services import (
    JobManager,
    PrometheusClient,
    PrometheusResult,
    LocalMetricsProvider,
    KubernetesMetricsProvider,
    MetricsSnapshot,
    PodMetrics,
    create_metrics_provider,
)


# =============================================================================
# JobManager Tests
# =============================================================================


class TestJobManager:
    """Tests for JobManager service."""

    def test_init_creates_empty_jobs_dict(self):
        """JobManager starts with no jobs."""
        manager = JobManager()
        assert manager.get_all_jobs() == []

    def test_register_job_adds_to_jobs(self):
        """register_job adds a job to the manager."""
        manager = JobManager()
        stop_event = Event()

        manager.register_job(
            job_id="test-job-1",
            job_type="cpu",
            config={"cores": 2, "duration_seconds": 60},
            processes=[],
            stop_event=stop_event,
        )

        jobs = manager.get_all_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "test-job-1"
        assert jobs[0]["type"] == "cpu"

    def test_get_job_returns_job_by_id(self):
        """get_job returns the correct job."""
        manager = JobManager()
        stop_event = Event()

        manager.register_job(
            job_id="test-job-1",
            job_type="memory",
            config={"size_mb": 100},
            processes=[],
            stop_event=stop_event,
        )

        job = manager.get_job("test-job-1")
        assert job is not None
        assert job["job_id"] == "test-job-1"

    def test_get_job_returns_none_for_unknown_id(self):
        """get_job returns None for unknown job ID."""
        manager = JobManager()
        assert manager.get_job("nonexistent") is None

    def test_get_all_jobs_filters_by_type(self):
        """get_all_jobs can filter by job type."""
        manager = JobManager()

        manager.register_job("cpu-1", "cpu", {}, [], Event())
        manager.register_job("mem-1", "memory", {}, [], Event())
        manager.register_job("cpu-2", "cpu", {}, [], Event())

        cpu_jobs = manager.get_all_jobs(job_type="cpu")
        assert len(cpu_jobs) == 2

        memory_jobs = manager.get_all_jobs(job_type="memory")
        assert len(memory_jobs) == 1

    def test_stop_job_sets_stop_event(self):
        """stop_job sets the stop event."""
        manager = JobManager()
        stop_event = Event()

        manager.register_job("test-job", "cpu", {}, [], stop_event)

        assert not stop_event.is_set()
        success = manager.stop_job("test-job")
        assert success
        assert stop_event.is_set()

    def test_stop_job_returns_false_for_unknown_id(self):
        """stop_job returns False for unknown job ID."""
        manager = JobManager()
        assert not manager.stop_job("nonexistent")

    def test_stop_all_jobs_stops_all_of_type(self):
        """stop_all_jobs stops all jobs of specified type."""
        manager = JobManager()

        event1 = Event()
        event2 = Event()
        event3 = Event()

        manager.register_job("cpu-1", "cpu", {}, [], event1)
        manager.register_job("mem-1", "memory", {}, [], event2)
        manager.register_job("cpu-2", "cpu", {}, [], event3)

        stopped = manager.stop_all_jobs(job_type="cpu")

        assert len(stopped) == 2
        assert event1.is_set()
        assert not event2.is_set()  # Memory job not stopped
        assert event3.is_set()

    def test_get_active_count_no_jobs(self):
        """get_active_count returns 0 when no jobs registered."""
        manager = JobManager()
        assert manager.get_active_count() == 0

    def test_get_active_count_with_job(self):
        """get_active_count counts jobs with 'running' status.

        Jobs registered with no processes have stored status 'running',
        so get_active_count returns 1 for a single registered job.
        """
        manager = JobManager()
        manager.register_job("job-1", "cpu", {}, [], Event())

        # Job with empty process list has stored status "running"
        # get_active_count counts jobs where status == "running"
        assert manager.get_active_count() == 1
        assert manager.get_active_count(job_type="cpu") == 1
        assert manager.get_active_count(job_type="memory") == 0


# =============================================================================
# PrometheusClient Tests
# =============================================================================


class TestPrometheusClient:
    """Tests for PrometheusClient service."""

    def test_init_with_custom_url(self):
        """PrometheusClient accepts custom URL."""
        client = PrometheusClient(url="http://custom:9090")
        assert client.url == "http://custom:9090"

    def test_init_with_custom_timeout(self):
        """PrometheusClient accepts custom timeout."""
        client = PrometheusClient(timeout=10)
        assert client.timeout == 10

    @patch("load_harness.services.prometheus.requests.get")
    def test_query_scalar_success(self, mock_get):
        """query_scalar returns value on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "result": [{"value": [1234567890, "42.5"]}]
            }
        }
        mock_get.return_value = mock_response

        client = PrometheusClient(url="http://test:9090")
        result = client.query_scalar("test_query")

        assert result == 42.5
        mock_get.assert_called_once()

    @patch("load_harness.services.prometheus.requests.get")
    def test_query_scalar_empty_result(self, mock_get):
        """query_scalar returns None for empty result."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"result": []}
        }
        mock_get.return_value = mock_response

        client = PrometheusClient(url="http://test:9090")
        result = client.query_scalar("test_query")

        assert result is None

    @patch("load_harness.services.prometheus.requests.get")
    def test_query_scalar_connection_error(self, mock_get):
        """query_scalar returns None on connection error."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()

        client = PrometheusClient(url="http://test:9090")
        result = client.query_scalar("test_query")

        assert result is None

    @patch("load_harness.services.prometheus.requests.get")
    def test_query_vector_success(self, mock_get):
        """query_vector returns list of results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "result": [
                    {"metric": {"pod": "pod-1"}, "value": [123, "10.5"]},
                    {"metric": {"pod": "pod-2"}, "value": [123, "20.5"]},
                ]
            }
        }
        mock_get.return_value = mock_response

        client = PrometheusClient(url="http://test:9090")
        results = client.query_vector("test_query")

        assert len(results) == 2
        assert isinstance(results[0], PrometheusResult)
        assert results[0].labels == {"pod": "pod-1"}
        assert results[0].value == 10.5

    @patch("load_harness.services.prometheus.requests.get")
    def test_query_vector_empty_result(self, mock_get):
        """query_vector returns empty list for empty result."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"result": []}
        }
        mock_get.return_value = mock_response

        client = PrometheusClient(url="http://test:9090")
        results = client.query_vector("test_query")

        assert results == []

    @patch("load_harness.services.prometheus.requests.get")
    def test_is_available_true(self, mock_get):
        """is_available returns True when Prometheus responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = PrometheusClient(url="http://test:9090")
        assert client.is_available() is True

    @patch("load_harness.services.prometheus.requests.get")
    def test_is_available_false(self, mock_get):
        """is_available returns False on error."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError()

        client = PrometheusClient(url="http://test:9090")
        assert client.is_available() is False


# =============================================================================
# MetricsProvider Tests
# =============================================================================


class TestLocalMetricsProvider:
    """Tests for LocalMetricsProvider."""

    def test_is_local_returns_true(self):
        """LocalMetricsProvider.is_local returns True."""
        provider = LocalMetricsProvider()
        assert provider.is_local is True

    def test_collect_pod_metrics_returns_single_pod(self):
        """LocalMetricsProvider returns single local pod entry."""
        provider = LocalMetricsProvider()
        pods = provider.collect_pod_metrics()

        assert len(pods) == 1
        assert pods[0].name == "load-harness-local"
        assert pods[0].short_name == "local"
        assert pods[0].status == "running"


class TestKubernetesMetricsProvider:
    """Tests for KubernetesMetricsProvider."""

    def test_is_local_returns_false(self):
        """KubernetesMetricsProvider.is_local returns False."""
        provider = KubernetesMetricsProvider()
        assert provider.is_local is False

    @patch.object(PrometheusClient, "query_scalar")
    def test_collect_metrics_queries_prometheus(self, mock_query):
        """KubernetesMetricsProvider queries Prometheus for metrics."""
        mock_query.return_value = 50.0

        provider = KubernetesMetricsProvider()
        metrics = provider.collect_metrics()

        # Should have called query_scalar multiple times
        assert mock_query.call_count >= 5
        assert isinstance(metrics, MetricsSnapshot)

    @patch.object(PrometheusClient, "query_vector")
    def test_collect_pod_metrics_queries_prometheus(self, mock_vector):
        """KubernetesMetricsProvider queries Prometheus for pod metrics."""
        mock_vector.return_value = [
            PrometheusResult(labels={"pod": "load-harness-abc"}, value=50.0),
            PrometheusResult(labels={"pod": "load-harness-xyz"}, value=30.0),
        ]

        provider = KubernetesMetricsProvider()
        pods = provider.collect_pod_metrics()

        assert len(pods) == 2
        assert all(isinstance(p, PodMetrics) for p in pods)


class TestCreateMetricsProvider:
    """Tests for create_metrics_provider factory function."""

    @patch.dict("os.environ", {"ENVIRONMENT": "local"})
    def test_creates_local_provider_for_local_env(self):
        """create_metrics_provider returns LocalMetricsProvider for local."""
        provider = create_metrics_provider()
        assert isinstance(provider, LocalMetricsProvider)

    @patch.dict("os.environ", {"ENVIRONMENT": "production"})
    def test_creates_k8s_provider_for_production_env(self):
        """create_metrics_provider returns KubernetesMetricsProvider for production."""
        provider = create_metrics_provider()
        assert isinstance(provider, KubernetesMetricsProvider)

    @patch.dict("os.environ", {"ENVIRONMENT": "staging"})
    def test_creates_k8s_provider_for_staging_env(self):
        """create_metrics_provider returns KubernetesMetricsProvider for staging."""
        provider = create_metrics_provider()
        assert isinstance(provider, KubernetesMetricsProvider)


# =============================================================================
# MetricsSnapshot Tests
# =============================================================================


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""

    def test_default_values(self):
        """MetricsSnapshot has correct default values."""
        snapshot = MetricsSnapshot()

        assert snapshot.pod_count is None
        assert snapshot.cpu_usage is None
        assert snapshot.memory_usage is None
        assert snapshot.request_rate is None
        assert snapshot.hpa_scaled is False
        assert snapshot.is_local is False

    def test_custom_values(self):
        """MetricsSnapshot accepts custom values."""
        snapshot = MetricsSnapshot(
            pod_count=3,
            cpu_usage=75.5,
            memory_usage=50.0,
            request_rate=100.0,
            hpa_scaled=True,
            is_local=True,
        )

        assert snapshot.pod_count == 3
        assert snapshot.cpu_usage == 75.5
        assert snapshot.hpa_scaled is True


# =============================================================================
# PodMetrics Tests
# =============================================================================


class TestPodMetrics:
    """Tests for PodMetrics dataclass."""

    def test_required_fields(self):
        """PodMetrics requires name and short_name."""
        pod = PodMetrics(name="test-pod", short_name="test")

        assert pod.name == "test-pod"
        assert pod.short_name == "test"
        assert pod.cpu_percent is None
        assert pod.memory_percent is None
        assert pod.status == "running"

    def test_custom_values(self):
        """PodMetrics accepts custom values."""
        pod = PodMetrics(
            name="load-harness-abc",
            short_name="abc",
            cpu_percent=80.5,
            memory_percent=60.0,
            status="running",
        )

        assert pod.cpu_percent == 80.5
        assert pod.memory_percent == 60.0
