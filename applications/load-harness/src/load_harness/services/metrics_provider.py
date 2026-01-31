"""Metrics provider abstraction for dashboard metrics.

Provides a clean abstraction over different metrics sources:
- LocalMetricsProvider: Uses psutil for local docker-compose environment
- KubernetesMetricsProvider: Uses Prometheus for Kubernetes clusters

This eliminates the large if/else block in the live_metrics route.
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from load_harness.constants import (
    PROM_QUERY_CPU_AVG,
    PROM_QUERY_CPU_MAX,
    PROM_QUERY_CPU_PER_POD,
    PROM_QUERY_MEMORY_AVG,
    PROM_QUERY_MEMORY_MAX,
    PROM_QUERY_MEMORY_PER_POD,
    PROM_QUERY_POD_COUNT,
    PROM_QUERY_REQUEST_RATE_CLUSTER,
    PROM_QUERY_REQUEST_RATE_LOCAL,
)
from load_harness.services.prometheus import PrometheusClient


@dataclass
class MetricsSnapshot:
    """Aggregated metrics snapshot for dashboard display."""

    pod_count: Optional[int] = None
    cpu_usage: Optional[float] = None
    cpu_usage_max: Optional[float] = None
    memory_usage: Optional[float] = None
    memory_usage_max: Optional[float] = None
    request_rate: Optional[float] = None
    hpa_scaled: bool = False
    is_local: bool = False


@dataclass
class PodMetrics:
    """Metrics for a single pod."""

    name: str
    short_name: str
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    status: str = "running"


class MetricsProvider(ABC):
    """Abstract base class for metrics providers."""

    @abstractmethod
    def collect_metrics(self) -> MetricsSnapshot:
        """Collect aggregated metrics snapshot."""
        pass

    @abstractmethod
    def collect_pod_metrics(self) -> List[PodMetrics]:
        """Collect per-pod metrics."""
        pass

    @property
    @abstractmethod
    def is_local(self) -> bool:
        """Whether this is a local environment provider."""
        pass


class LocalMetricsProvider(MetricsProvider):
    """Metrics provider for local docker-compose environment.

    Uses psutil to measure actual process CPU/Memory usage since
    Kubernetes metrics (cAdvisor) are not available locally.
    """

    def __init__(
        self,
        prometheus_client: Optional[PrometheusClient] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize local metrics provider.

        Args:
            prometheus_client: Optional Prometheus client for request rate.
            logger: Optional logger instance.
        """
        self._prometheus = prometheus_client or PrometheusClient()
        self._logger = logger or logging.getLogger(self.__class__.__name__)

    @property
    def is_local(self) -> bool:
        return True

    def collect_metrics(self) -> MetricsSnapshot:
        """Collect metrics using psutil for local process measurement."""
        import psutil

        cpu_usage = None
        memory_usage = None

        try:
            # Find all Python processes in the container
            python_procs = []
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    exe = proc.info.get("exe") or ""
                    name = proc.info.get("name") or ""
                    if "python" in exe.lower() or "python" in name.lower():
                        python_procs.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # First call to initialize CPU percent tracking
            for proc in python_procs:
                try:
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Brief sleep to allow CPU measurement
            time.sleep(0.2)

            # Second call to get actual CPU usage
            total_cpu = 0.0
            total_mem = 0
            for proc in python_procs:
                try:
                    total_cpu += proc.cpu_percent()
                    total_mem += proc.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Normalize CPU by core count
            cpu_count = psutil.cpu_count() or 1
            cpu_usage = total_cpu / cpu_count

            # Memory as percentage of total system memory
            total_memory = psutil.virtual_memory().total
            memory_usage = (total_mem / total_memory) * 100

        except Exception as e:
            self._logger.warning("Failed to collect local metrics: %s", e)

        # Request rate from Prometheus (if available)
        request_rate = self._prometheus.query_scalar(PROM_QUERY_REQUEST_RATE_LOCAL)

        return MetricsSnapshot(
            pod_count=1,
            cpu_usage=cpu_usage,
            cpu_usage_max=cpu_usage,  # Same as avg in local mode
            memory_usage=memory_usage,
            memory_usage_max=memory_usage,  # Same as avg in local mode
            request_rate=request_rate,
            hpa_scaled=False,
            is_local=True,
        )

    def collect_pod_metrics(self) -> List[PodMetrics]:
        """Return single simulated pod entry for local environment."""
        return [
            PodMetrics(
                name="load-harness-local",
                short_name="local",
                cpu_percent=None,  # No cAdvisor metrics locally
                memory_percent=None,
                status="running",
            )
        ]


class KubernetesMetricsProvider(MetricsProvider):
    """Metrics provider for Kubernetes cluster environment.

    Uses Prometheus to query cAdvisor and kube-state-metrics for
    container resource usage across all load-harness pods.
    """

    def __init__(
        self,
        prometheus_client: Optional[PrometheusClient] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize Kubernetes metrics provider.

        Args:
            prometheus_client: Optional Prometheus client.
            logger: Optional logger instance.
        """
        self._prometheus = prometheus_client or PrometheusClient()
        self._logger = logger or logging.getLogger(self.__class__.__name__)

    @property
    def is_local(self) -> bool:
        return False

    def collect_metrics(self) -> MetricsSnapshot:
        """Collect cluster-wide metrics from Prometheus."""
        pod_count = self._prometheus.query_scalar(PROM_QUERY_POD_COUNT)
        cpu_usage = self._prometheus.query_scalar(PROM_QUERY_CPU_AVG)
        cpu_usage_max = self._prometheus.query_scalar(PROM_QUERY_CPU_MAX)
        memory_usage = self._prometheus.query_scalar(PROM_QUERY_MEMORY_AVG)
        memory_usage_max = self._prometheus.query_scalar(PROM_QUERY_MEMORY_MAX)
        request_rate = self._prometheus.query_scalar(PROM_QUERY_REQUEST_RATE_CLUSTER)

        # HPA status: check if we've scaled beyond minimum (1)
        hpa_scaled = pod_count is not None and pod_count > 1

        return MetricsSnapshot(
            pod_count=int(pod_count) if pod_count is not None else None,
            cpu_usage=cpu_usage,
            cpu_usage_max=cpu_usage_max,
            memory_usage=memory_usage,
            memory_usage_max=memory_usage_max,
            request_rate=request_rate,
            hpa_scaled=hpa_scaled,
            is_local=False,
        )

    def collect_pod_metrics(self) -> List[PodMetrics]:
        """Collect per-pod CPU and memory metrics."""
        cpu_results = self._prometheus.query_vector(PROM_QUERY_CPU_PER_POD)
        memory_results = self._prometheus.query_vector(PROM_QUERY_MEMORY_PER_POD)

        # Build pod data dict keyed by pod name
        pods: Dict[str, PodMetrics] = {}

        for result in cpu_results:
            pod_name = result.labels.get("pod", "unknown")
            short_name = pod_name.split("-")[-1][:8] if pod_name else "unknown"
            pods[pod_name] = PodMetrics(
                name=pod_name,
                short_name=short_name,
                cpu_percent=round(result.value, 1),
                status="running",
            )

        # Add memory data
        for result in memory_results:
            pod_name = result.labels.get("pod", "unknown")
            if pod_name in pods:
                pods[pod_name].memory_percent = round(result.value, 1)

        # Sort pods by name for consistent ordering
        return sorted(pods.values(), key=lambda p: p.name)


def create_metrics_provider(
    prometheus_client: Optional[PrometheusClient] = None,
    logger: Optional[logging.Logger] = None,
) -> MetricsProvider:
    """Factory function to create the appropriate metrics provider.

    Args:
        prometheus_client: Optional Prometheus client to inject.
        logger: Optional logger instance.

    Returns:
        LocalMetricsProvider for local environment, KubernetesMetricsProvider otherwise.
    """
    is_local = os.environ.get("ENVIRONMENT", "local") == "local"

    if is_local:
        return LocalMetricsProvider(prometheus_client, logger)
    return KubernetesMetricsProvider(prometheus_client, logger)
