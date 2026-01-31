"""Application constants for load-harness.

Centralizes magic numbers and configuration values to improve maintainability.
"""

# =============================================================================
# CPU Load Limits
# =============================================================================
CPU_MAX_CORES = 16
CPU_MIN_CORES = 1
CPU_DEFAULT_CORES = 1

CPU_MAX_DURATION_SECONDS = 900  # 15 minutes
CPU_MIN_DURATION_SECONDS = 10
CPU_DEFAULT_DURATION_SECONDS = 60

CPU_MAX_INTENSITY = 10
CPU_MIN_INTENSITY = 1
CPU_DEFAULT_INTENSITY = 5

# Synchronous CPU work endpoint limits
CPU_WORK_MAX_ITERATIONS = 10_000_000
CPU_WORK_MIN_ITERATIONS = 1_000
CPU_WORK_DEFAULT_ITERATIONS = 100_000

# =============================================================================
# Memory Load Limits
# =============================================================================
MEMORY_MAX_SIZE_MB = 2048
MEMORY_MIN_SIZE_MB = 1
MEMORY_DEFAULT_SIZE_MB = 50

MEMORY_MAX_DURATION_SECONDS = 300  # 5 minutes
MEMORY_MIN_DURATION_SECONDS = 5
MEMORY_DEFAULT_DURATION_SECONDS = 30

# Legacy sync endpoint limits
MEMORY_SYNC_MAX_DURATION_MS = 120_000  # 2 minutes
MEMORY_SYNC_MIN_DURATION_MS = 1
MEMORY_SYNC_DEFAULT_DURATION_MS = 1000

# =============================================================================
# Process Management
# =============================================================================
PROCESS_TERMINATE_TIMEOUT = 1  # seconds
JOB_CLEANUP_BUFFER_SECONDS = 5  # extra time before cleanup

# Memory page size for allocation
MEMORY_PAGE_SIZE_BYTES = 4096

# =============================================================================
# Job ID Prefixes
# =============================================================================
CPU_JOB_PREFIX = "job_"
MEMORY_JOB_PREFIX = "mem_"

# =============================================================================
# HTTP/API Settings
# =============================================================================
API_REQUEST_TIMEOUT = 10  # seconds
PROMETHEUS_QUERY_TIMEOUT = 5  # seconds

# =============================================================================
# Prometheus Query Templates
# =============================================================================

# Pod count query
PROM_QUERY_POD_COUNT = (
    'count(kube_pod_status_phase{namespace="applications", '
    'pod=~"load-harness.*", phase="Running"})'
)

# CPU usage queries (percentage of 100m limit)
PROM_QUERY_CPU_AVG = (
    'avg(rate(container_cpu_usage_seconds_total{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"}[1m])) * 100 / 0.1'
)

PROM_QUERY_CPU_MAX = (
    'max(rate(container_cpu_usage_seconds_total{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"}[1m])) * 100 / 0.1'
)

PROM_QUERY_CPU_PER_POD = (
    'rate(container_cpu_usage_seconds_total{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"}[1m]) * 100 / 0.1'
)

# Memory usage queries (percentage of 1Gi limit)
PROM_QUERY_MEMORY_AVG = (
    'avg(container_memory_working_set_bytes{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"}) / (1024 * 1024 * 1024) * 100'
)

PROM_QUERY_MEMORY_MAX = (
    'max(container_memory_working_set_bytes{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"}) / (1024 * 1024 * 1024) * 100'
)

PROM_QUERY_MEMORY_PER_POD = (
    'container_memory_working_set_bytes{namespace="applications", '
    'pod=~"load-harness.*", container="load-harness"} / (1024 * 1024 * 1024) * 100'
)

# Request rate queries
PROM_QUERY_REQUEST_RATE_LOCAL = (
    'sum(rate(flask_http_request_total{job="load-harness"}[1m]))'
)

PROM_QUERY_REQUEST_RATE_CLUSTER = (
    'sum(rate(flask_http_request_total{namespace="applications", '
    'pod=~"load-harness.*"}[1m]))'
)

# =============================================================================
# Cluster Load Test Limits
# =============================================================================
CLUSTER_MAX_CONCURRENCY = 100
CLUSTER_MIN_CONCURRENCY = 1
CLUSTER_DEFAULT_CONCURRENCY = 10
CLUSTER_REQUEST_TIMEOUT = 120  # seconds
