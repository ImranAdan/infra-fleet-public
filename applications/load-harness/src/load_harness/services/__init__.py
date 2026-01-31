"""Services module for load-harness.

This module provides service abstractions for:
- Job management (JobManager)
- Prometheus metrics querying (PrometheusClient)
- Dashboard metrics collection (MetricsProvider)
"""

from load_harness.services.job_manager import JobManager
from load_harness.services.prometheus import PrometheusClient, PrometheusResult
from load_harness.services.metrics_provider import (
    MetricsProvider,
    MetricsSnapshot,
    PodMetrics,
    LocalMetricsProvider,
    KubernetesMetricsProvider,
    create_metrics_provider,
)

__all__ = [
    "JobManager",
    "PrometheusClient",
    "PrometheusResult",
    "MetricsProvider",
    "MetricsSnapshot",
    "PodMetrics",
    "LocalMetricsProvider",
    "KubernetesMetricsProvider",
    "create_metrics_provider",
]
