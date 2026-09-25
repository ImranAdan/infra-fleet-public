"""LoadHarness service providing synthetic workload generation endpoints.

This module contains the LoadHarnessService class which registers all API routes
and handles load generation for CPU and memory workloads.
"""

import math
import os
import time
import uuid
import logging
import multiprocessing
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import psutil
from flask import jsonify, request
from flasgger import swag_from

from load_harness.constants import (
    CPU_MAX_CORES,
    CPU_MIN_CORES,
    CPU_DEFAULT_CORES,
    CPU_MAX_DURATION_SECONDS,
    CPU_MIN_DURATION_SECONDS,
    CPU_DEFAULT_DURATION_SECONDS,
    CPU_MAX_INTENSITY,
    CPU_MIN_INTENSITY,
    CPU_DEFAULT_INTENSITY,
    CPU_WORK_MAX_ITERATIONS,
    CPU_WORK_MIN_ITERATIONS,
    CPU_WORK_DEFAULT_ITERATIONS,
    CPU_WORK_MAX_CONCURRENCY,
    MEMORY_MAX_SIZE_MB,
    MEMORY_LIMIT_HEADROOM,
    MEMORY_MIN_SIZE_MB,
    MEMORY_DEFAULT_SIZE_MB,
    MEMORY_MAX_DURATION_SECONDS,
    MEMORY_MIN_DURATION_SECONDS,
    MEMORY_DEFAULT_DURATION_SECONDS,
    MEMORY_SYNC_MAX_DURATION_MS,
    MEMORY_SYNC_MIN_DURATION_MS,
    MEMORY_SYNC_DEFAULT_DURATION_MS,
    MEMORY_PAGE_SIZE_BYTES,
    CPU_JOB_PREFIX,
    MEMORY_JOB_PREFIX,
)
from load_harness.openapi_specs import (
    APP_INFO_SPEC,
    HEALTH_CHECK_SPEC,
    READY_SPEC,
    VERSION_SPEC,
    SYSTEM_INFO_SPEC,
    MEMORY_LOAD_SPEC,
    MEMORY_LOAD_START_SPEC,
    MEMORY_LOAD_STATUS_SPEC,
    MEMORY_LOAD_STOP_SPEC,
    CPU_LOAD_START_SPEC,
    CPU_LOAD_STATUS_SPEC,
    CPU_LOAD_STOP_SPEC,
    CPU_LOAD_WORK_SPEC,
)
from load_harness.services.job_manager import JobManager
from load_harness.services.memory_budget import MemoryBudget
from load_harness.workers.cpu_worker import cpu_worker_target
from load_harness.workers.memory_worker import memory_worker_target


# Request handlers run inside an already multithreaded web process. Forking at
# that point can inherit locked runtime state and is deprecated by Python 3.13.
# Spawn gives each synthetic worker a clean interpreter instead.
_PROCESS_CONTEXT = multiprocessing.get_context("spawn")


def _get_cpu_limit_cores() -> Optional[float]:
    """The container's CPU limit in cores (0.5 for a 500m limit); None if unlimited."""
    try:
        with open('/sys/fs/cgroup/cpu.max', 'r') as f:
            quota, period = f.read().split()
        return None if quota == 'max' else int(quota) / int(period)
    except (FileNotFoundError, ValueError, PermissionError):
        pass
    try:
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'r') as f:
            quota_us = int(f.read().strip())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'r') as f:
            period_us = int(f.read().strip())
        return quota_us / period_us if quota_us > 0 else None
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def _get_available_cpu_cores() -> int:
    """
    Get the number of CPU cores available, respecting cgroup limits (K8s).

    In Kubernetes, CPU limits are enforced via cgroups. This function
    checks cgroup quotas first, falling back to system CPU count.
    """
    # Try cgroup v2 first (newer K8s versions)
    try:
        with open('/sys/fs/cgroup/cpu.max', 'r') as f:
            content = f.read().strip()
            if content != 'max':
                quota, period = content.split()
                quota = int(quota)
                period = int(period)
                if quota > 0:
                    return max(1, quota // period)
    except (FileNotFoundError, ValueError, PermissionError):
        pass

    # Try cgroup v1
    try:
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us', 'r') as f:
            quota = int(f.read().strip())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us', 'r') as f:
            period = int(f.read().strip())
        if quota > 0:
            return max(1, quota // period)
    except (FileNotFoundError, ValueError, PermissionError):
        pass

    # Fallback to system CPU count
    return multiprocessing.cpu_count()


def _get_memory_limit_mb() -> int:
    """
    Get the memory ceiling a single load job may request, respecting cgroups.

    MEMORY_MAX_SIZE_MB alone is not safe: it is a static 2048 while the
    container limit is 1Gi, so an in-range request allocated twice the cgroup
    limit and the OOM killer ended the pod. Derive the real limit the way
    _get_available_cpu_cores derives the CPU count, keeping headroom for the
    web process itself.

    This is the PER-JOB ceiling only. On its own it does not stop several
    concurrent jobs summing past the container limit: three concurrent 600MB
    requests in a 1Gi container were each individually valid and still drove
    the cgroup to an OOM kill. MemoryBudget enforces the aggregate across
    Gunicorn workers, and the same three requests now admit one and reject two
    with a 409.

    Returns:
        The lower of MEMORY_MAX_SIZE_MB and this job's share of the cgroup limit
    """
    limit_bytes = None

    # cgroup v2
    try:
        with open('/sys/fs/cgroup/memory.max', 'r') as f:
            content = f.read().strip()
            if content != 'max':
                limit_bytes = int(content)
    except (FileNotFoundError, ValueError, PermissionError):
        pass

    # cgroup v1. An unlimited cgroup reports a sentinel near 2^63, so treat an
    # implausibly large value as "no limit" rather than as a real ceiling.
    if limit_bytes is None:
        try:
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                value = int(f.read().strip())
            if value < (1 << 62):
                limit_bytes = value
        except (FileNotFoundError, ValueError, PermissionError):
            pass

    if not limit_bytes or limit_bytes <= 0:
        return MEMORY_MAX_SIZE_MB

    budget_mb = int((limit_bytes // (1024 * 1024)) * MEMORY_LIMIT_HEADROOM)
    return max(MEMORY_MIN_SIZE_MB, min(MEMORY_MAX_SIZE_MB, budget_mb))


def _new_job_id(prefix: str) -> str:
    """
    Generate a unique job ID.

    A millisecond timestamp alone collides: two jobs started in the same
    millisecond produced the same ID, and register_job silently overwrote the
    first, orphaning its worker processes. The timestamp stays because it keeps
    IDs sortable in logs; the suffix is what makes them unique.

    Args:
        prefix: Job type prefix, e.g. CPU_JOB_PREFIX

    Returns:
        A unique, roughly sortable job identifier
    """
    return f"{prefix}{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


class LoadHarnessService:
    """
    Encapsulates all load-harness endpoints and related logic.
    """

    def __init__(self, app, metrics=None, job_manager: Optional[JobManager] = None):
        """
        Initialize LoadHarnessService with Flask app and optional dependencies.

        Args:
            app: Flask application instance
            metrics: PrometheusMetrics instance (optional)
            job_manager: JobManager instance for job lifecycle management.
                        If not provided, a new instance is created.
        """
        self.app = app
        self.metrics = metrics
        self.logger = logging.getLogger(self.__class__.__name__)
        self.job_manager = job_manager or JobManager(logger=self.logger)
        self.available_cores = _get_available_cpu_cores()
        self.memory_limit_mb = _get_memory_limit_mb()
        self.memory_budget = MemoryBudget(self.memory_limit_mb)
        self.cpu_work_slots = threading.BoundedSemaphore(CPU_WORK_MAX_CONCURRENCY)

        # The dashboard blueprint runs in this same process and used to reach
        # these endpoints over HTTP against 127.0.0.1, which deadlocked the
        # gunicorn worker pool. It now calls the methods below directly.
        app.extensions["load_harness"] = self

        self._register_routes()

    def try_acquire_cpu_work_slot(self) -> bool:
        """Reserve one long-lived request slot without making the caller wait."""
        return self.cpu_work_slots.acquire(blocking=False)

    def release_cpu_work_slot(self) -> None:
        """Return a long-lived request slot reserved by this process."""
        self.cpu_work_slots.release()

    def _register_routes(self):
        """Wire endpoints to Flask routes."""
        self.app.add_url_rule("/", "app_info", self.app_info, methods=["GET"])
        self.app.add_url_rule("/health", "health_check", self.health_check, methods=["GET"])
        self.app.add_url_rule("/ready", "ready_check", self.ready, methods=["GET"])
        self.app.add_url_rule("/version", "version", self.version, methods=["GET"])
        self.app.add_url_rule("/system/info", "system_info", self.system_info, methods=["GET"])

        # Memory load endpoints (non-blocking, multi-process)
        self.app.add_url_rule("/load/memory", "memory_load", self.memory_load, methods=["POST"])
        self.app.add_url_rule("/load/memory/status", "memory_load_status", self.memory_load_status, methods=["GET"])
        self.app.add_url_rule("/load/memory/stop", "memory_load_stop", self.memory_load_stop, methods=["POST"])
        # Legacy blocking memory endpoint
        self.app.add_url_rule("/load/memory/sync", "memory_load_sync", self.memory_load_sync, methods=["POST"])

        # CPU load endpoints (non-blocking, multi-process)
        self.app.add_url_rule("/load/cpu", "cpu_load", self.cpu_load, methods=["POST"])
        self.app.add_url_rule("/load/cpu/status", "cpu_load_status", self.cpu_load_status, methods=["GET"])
        self.app.add_url_rule("/load/cpu/stop", "cpu_load_stop", self.cpu_load_stop, methods=["POST"])
        # Synchronous CPU work endpoint (for distributed load testing)
        self.app.add_url_rule("/load/cpu/work", "cpu_load_work", self.cpu_load_work, methods=["POST"])

    # ---- Endpoints ----

    @swag_from(APP_INFO_SPEC)
    def app_info(self):
        return jsonify({
            "message": "Load Harness - Synthetic Workload Generator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": os.getenv("APP_VERSION", "dev"),
            "environment": os.getenv("ENVIRONMENT", "local"),
        })

    @swag_from(HEALTH_CHECK_SPEC)
    def health_check(self):
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    @swag_from(READY_SPEC)
    def ready(self):
        """Readiness probe for Kubernetes."""
        return jsonify({
            "status": "ready",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @swag_from(VERSION_SPEC)
    def version(self):
        """Return version and build information."""
        import sys
        import socket

        # Get pod/hostname for Kubernetes deployment tracking
        hostname = socket.gethostname()

        return jsonify({
            "version": os.getenv("APP_VERSION", "dev"),
            "environment": os.getenv("ENVIRONMENT", "local"),
            "build": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            },
            "deployment": {
                "pod_name": hostname,
                "namespace": "applications",  # Could be env var in future
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_system_info(self) -> Dict[str, Any]:
        """Return system information including available CPU cores.

        Callable directly by the dashboard; system_info wraps it for HTTP.
        """
        cpu_cores = _get_available_cpu_cores()

        # Get memory info
        try:
            memory = psutil.virtual_memory()
            memory_total_mb = memory.total // (1024 * 1024)
            memory_available_mb = memory.available // (1024 * 1024)
        except Exception:
            memory_total_mb = None
            memory_available_mb = None

        return {
            "cpu_cores": cpu_cores,
            "cpu_limit_cores": _get_cpu_limit_cores(),
            "cpu_cores_physical": multiprocessing.cpu_count(),
            "memory_total_mb": memory_total_mb,
            "memory_available_mb": memory_available_mb,
            "memory_limit_mb": self.memory_limit_mb,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @swag_from(SYSTEM_INFO_SPEC)
    def system_info(self):
        """Return system information including available CPU cores."""
        return jsonify(self.get_system_info())

    def start_memory_load(
        self, size_mb: Any, duration_seconds: Any
    ) -> Tuple[Dict[str, Any], int]:
        """Validate and start a memory load job.

        Callable directly by the dashboard; memory_load wraps it for HTTP.

        Returns:
            (response body, HTTP status code)
        """
        # Validate inputs. The ceiling is the cgroup-derived limit, not the
        # static constant - allocating past the container limit OOM-kills the
        # pod, and that was reachable with a documented in-range request.
        if not isinstance(size_mb, (int, float)) or isinstance(size_mb, bool) \
                or size_mb < MEMORY_MIN_SIZE_MB or size_mb > self.memory_limit_mb:
            return {
                "error": f"size_mb must be between {MEMORY_MIN_SIZE_MB} and {self.memory_limit_mb}"
            }, 400

        if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool) \
                or duration_seconds < MEMORY_MIN_DURATION_SECONDS or duration_seconds > MEMORY_MAX_DURATION_SECONDS:
            return {
                "error": f"duration_seconds must be between {MEMORY_MIN_DURATION_SECONDS} and {MEMORY_MAX_DURATION_SECONDS}"
            }, 400

        reserved_size_mb = int(size_mb)
        reservation_id = self.memory_budget.reserve(reserved_size_mb)
        if reservation_id is None:
            return {
                "error": "Requested memory exceeds the pod capacity remaining for load jobs"
            }, 409

        job_id = _new_job_id(MEMORY_JOB_PREFIX)

        self.logger.info(
            "Starting memory load: job_id=%s size_mb=%s duration=%ss",
            job_id, size_mb, duration_seconds,
        )

        # Create stop event for graceful termination
        stop_event = _PROCESS_CONTEXT.Event()

        try:
            process = _PROCESS_CONTEXT.Process(
                target=memory_worker_target,
                args=(job_id, reserved_size_mb, duration_seconds, stop_event),
                name=job_id,
            )
            process.start()
            self.memory_budget.activate(reservation_id, process.pid)

            config = {
                "size_mb": reserved_size_mb,
                "duration_seconds": duration_seconds,
                "memory_reservation_id": reservation_id,
            }
            self.job_manager.register_job(
                job_id=job_id,
                job_type="memory",
                config=config,
                processes=[process],
                stop_event=stop_event,
            )

            # JobManager invokes callbacks after the child has been reaped.
            self.job_manager.schedule_cleanup(
                job_id,
                duration_seconds,
                callback=lambda: self.memory_budget.release(reservation_id),
            )
        except BaseException:
            self.memory_budget.release(reservation_id)
            if "process" in locals() and process.is_alive():
                process.terminate()
                process.join()
            raise

        return {
            "status": "started",
            "job_id": job_id,
            "size_mb": reserved_size_mb,
            "duration_seconds": duration_seconds,
            "message": f"Memory load started: {int(size_mb)}MB for {duration_seconds}s. Health probes remain responsive.",
            "check_status": "/load/memory/status",
            "stop_endpoint": "/load/memory/stop",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, 200

    @swag_from(MEMORY_LOAD_START_SPEC)
    def memory_load(self):
        """Start memory load using background worker process."""
        data = request.get_json() or {}
        body, status = self.start_memory_load(
            data.get("size_mb", MEMORY_DEFAULT_SIZE_MB),
            data.get("duration_seconds", MEMORY_DEFAULT_DURATION_SECONDS),
        )
        return jsonify(body), status

    @swag_from(MEMORY_LOAD_STATUS_SPEC)
    def memory_load_status(self):
        """Get status of memory load jobs."""
        jobs = self.job_manager.get_all_jobs(job_type="memory")

        # Format jobs for API response
        formatted_jobs = []
        for job in jobs:
            formatted_jobs.append({
                "job_id": job.get("job_id"),
                "status": job.get("status", "completed"),
                "size_mb": job.get("config", {}).get("size_mb", 0),
                "duration_seconds": job.get("config", {}).get("duration_seconds", 0),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "stopped_at": job.get("stopped_at"),
            })

        return jsonify({
            "active_jobs": len([j for j in formatted_jobs if j["status"] == "running"]),
            "total_jobs": len(formatted_jobs),
            "jobs": formatted_jobs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @swag_from(MEMORY_LOAD_STOP_SPEC)
    def memory_load_stop(self):
        """Stop memory load workers and release memory."""
        data = request.get_json() or {}
        target_job_id = data.get("job_id")

        if target_job_id:
            # Stop specific job
            job = self.job_manager.get_job(target_job_id)
            success = self.job_manager.stop_job(target_job_id)
            if not success:
                return jsonify({"error": f"Job {target_job_id} not found"}), 404
            self.memory_budget.release(
                job.get("config", {}).get("memory_reservation_id")
            )
            stopped_jobs = [target_job_id]
        else:
            # Stop all memory jobs
            jobs = self.job_manager.get_all_jobs(job_type="memory")
            stopped_jobs = self.job_manager.stop_all_jobs(job_type="memory")
            for job in jobs:
                if job.get("job_id") in stopped_jobs:
                    self.memory_budget.release(
                        job.get("config", {}).get("memory_reservation_id")
                    )

        return jsonify({
            "status": "stopped",
            "stopped_jobs": stopped_jobs,
            "count": len(stopped_jobs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @swag_from(MEMORY_LOAD_SPEC)
    def memory_load_sync(self):
        """Generate memory-intensive load synchronously (blocking). Legacy endpoint."""
        data = request.get_json() or {}
        size_mb = data.get("size_mb", MEMORY_DEFAULT_SIZE_MB)
        duration_ms = data.get("duration_ms", MEMORY_SYNC_DEFAULT_DURATION_MS)

        # This endpoint allocates in the web worker itself rather than a child
        # process, so exceeding the cgroup limit kills the process serving the
        # request. Same ceiling as the async path.
        if not isinstance(size_mb, (int, float)) or isinstance(size_mb, bool) \
                or size_mb < MEMORY_MIN_SIZE_MB or size_mb > self.memory_limit_mb:
            return jsonify({
                "error": f"size_mb must be between {MEMORY_MIN_SIZE_MB} and {self.memory_limit_mb}"
            }), 400

        if not isinstance(duration_ms, (int, float)) or isinstance(duration_ms, bool) \
                or duration_ms < MEMORY_SYNC_MIN_DURATION_MS or duration_ms > MEMORY_SYNC_MAX_DURATION_MS:
            return jsonify({
                "error": f"duration_ms must be between {MEMORY_SYNC_MIN_DURATION_MS} and {MEMORY_SYNC_MAX_DURATION_MS}"
            }), 400

        self.logger.info(
            "Starting sync memory load: size_mb=%s duration_ms=%s",
            size_mb,
            duration_ms,
        )

        reservation_id = self.memory_budget.reserve(int(size_mb))
        if reservation_id is None:
            return jsonify({
                "error": "Requested memory exceeds the pod capacity remaining for load jobs"
            }), 409

        start_time = time.time()
        try:
            bytes_to_allocate = int(size_mb * 1024 * 1024)
            memory_block = bytearray(bytes_to_allocate)

            # Touch all pages using constant page size
            for i in range(0, len(memory_block), MEMORY_PAGE_SIZE_BYTES):
                memory_block[i] = i % 256

            allocation_time_ms = (time.time() - start_time) * 1000.0
            time.sleep(duration_ms / 1000.0)
            actual_duration_ms = (time.time() - start_time) * 1000.0
        finally:
            self.memory_budget.release(reservation_id)

        self.logger.info(
            "Completed sync memory load: size_mb=%s requested=%sms actual=%sms",
            size_mb,
            duration_ms,
            round(actual_duration_ms, 2),
        )

        return jsonify({
            "status": "completed",
            "requested_size_mb": int(size_mb),
            "actual_bytes_allocated": bytes_to_allocate,
            "requested_duration_ms": duration_ms,
            "actual_duration_ms": round(actual_duration_ms, 2),
            "allocation_time_ms": round(allocation_time_ms, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def start_cpu_load(
        self, cores: Any, duration_seconds: Any, intensity: Any
    ) -> Tuple[Dict[str, Any], int]:
        """Validate and start a CPU load job.

        Callable directly by the dashboard; cpu_load wraps it for HTTP.

        Returns:
            (response body, HTTP status code)
        """
        # Validate inputs using constants
        if not isinstance(cores, int) or isinstance(cores, bool) \
                or cores < CPU_MIN_CORES or cores > CPU_MAX_CORES:
            return {
                "error": f"cores must be between {CPU_MIN_CORES} and {CPU_MAX_CORES}"
            }, 400

        if cores > self.available_cores:
            return {
                "error": f"cores ({cores}) exceeds available cores ({self.available_cores})"
            }, 400

        if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool) \
                or duration_seconds < CPU_MIN_DURATION_SECONDS or duration_seconds > CPU_MAX_DURATION_SECONDS:
            return {
                "error": f"duration_seconds must be between {CPU_MIN_DURATION_SECONDS} and {CPU_MAX_DURATION_SECONDS}"
            }, 400

        if not isinstance(intensity, int) or isinstance(intensity, bool) \
                or intensity < CPU_MIN_INTENSITY or intensity > CPU_MAX_INTENSITY:
            return {
                "error": f"intensity must be between {CPU_MIN_INTENSITY} and {CPU_MAX_INTENSITY}"
            }, 400

        job_id = _new_job_id(CPU_JOB_PREFIX)

        self.logger.info(
            "Starting CPU load: job_id=%s cores=%s duration=%ss intensity=%s",
            job_id, cores, duration_seconds, intensity,
        )

        # Create stop event for graceful termination
        stop_event = _PROCESS_CONTEXT.Event()

        # Start worker processes (one per core) using the extracted worker target
        processes = []
        for i in range(cores):
            worker_id = f"{job_id}_worker_{i}"
            p = _PROCESS_CONTEXT.Process(
                target=cpu_worker_target,
                args=(worker_id, duration_seconds, intensity, stop_event),
                name=worker_id,
            )
            p.start()
            processes.append(p)

        # Register job with JobManager
        config = {
            "cores": cores,
            "duration_seconds": duration_seconds,
            "intensity": intensity,
        }
        self.job_manager.register_job(
            job_id=job_id,
            job_type="cpu",
            config=config,
            processes=processes,
            stop_event=stop_event,
        )

        # Schedule automatic cleanup
        self.job_manager.schedule_cleanup(job_id, duration_seconds)

        # A worker per requested core, but the kernel caps the container at its
        # CPU limit; say so rather than claim cores it cannot have.
        limit = _get_cpu_limit_cores()
        message = f"CPU load started with {cores} worker(s)."
        if limit is not None and limit < cores:
            message += f" The container is limited to {limit:g} core(s), which they share."
        message += " Health probes remain responsive."
        return {
            "status": "started",
            "job_id": job_id,
            "cores": cores,
            "duration_seconds": duration_seconds,
            "intensity": intensity,
            "cpu_limit_cores": limit,
            "message": message,
            "check_status": "/load/cpu/status",
            "stop_endpoint": "/load/cpu/stop",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, 200

    @swag_from(CPU_LOAD_START_SPEC)
    def cpu_load(self):
        """Start CPU load using background worker processes."""
        data = request.get_json() or {}
        body, status = self.start_cpu_load(
            data.get("cores", CPU_DEFAULT_CORES),
            data.get("duration_seconds", CPU_DEFAULT_DURATION_SECONDS),
            data.get("intensity", CPU_DEFAULT_INTENSITY),
        )
        return jsonify(body), status

    def get_cpu_status(self) -> Dict[str, Any]:
        """Get status of CPU load jobs.

        Callable directly by the dashboard; cpu_load_status wraps it for HTTP.
        """
        jobs = self.job_manager.get_all_jobs(job_type="cpu")

        # Format jobs for API response (JobManager already provides cores_active)
        formatted_jobs = []
        for job in jobs:
            formatted_jobs.append({
                "job_id": job.get("job_id"),
                "status": job.get("status", "completed"),
                "cores_requested": job.get("cores_requested", job.get("config", {}).get("cores", 0)),
                "cores_active": job.get("cores_active", 0),
                "duration_seconds": job.get("config", {}).get("duration_seconds", 0),
                "intensity": job.get("config", {}).get("intensity", 0),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "stopped_at": job.get("stopped_at"),
            })

        return {
            "active_jobs": len([j for j in formatted_jobs if j["status"] == "running"]),
            "total_jobs": len(formatted_jobs),
            "jobs": formatted_jobs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @swag_from(CPU_LOAD_STATUS_SPEC)
    def cpu_load_status(self):
        """Get status of CPU load jobs."""
        return jsonify(self.get_cpu_status())

    @swag_from(CPU_LOAD_STOP_SPEC)
    def cpu_load_stop(self):
        """Stop CPU load workers."""
        data = request.get_json() or {}
        target_job_id = data.get("job_id")

        if target_job_id:
            # Stop specific job
            success = self.job_manager.stop_job(target_job_id)
            if not success:
                return jsonify({"error": f"Job {target_job_id} not found"}), 404
            stopped_jobs = [target_job_id]
        else:
            # Stop all CPU jobs
            stopped_jobs = self.job_manager.stop_all_jobs(job_type="cpu")

        return jsonify({
            "status": "stopped",
            "stopped_jobs": stopped_jobs,
            "count": len(stopped_jobs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def run_cpu_work(self, iterations: Any) -> Tuple[Dict[str, Any], int]:
        """Run synchronous CPU work and return the result.

        Callable directly by the dashboard; cpu_load_work wraps it for HTTP.

        Returns:
            (response body, HTTP status code)
        """
        # Validate iterations using constants
        if not isinstance(iterations, int) or isinstance(iterations, bool) \
                or iterations < CPU_WORK_MIN_ITERATIONS or iterations > CPU_WORK_MAX_ITERATIONS:
            return {
                "error": f"iterations must be between {CPU_WORK_MIN_ITERATIONS:,} and {CPU_WORK_MAX_ITERATIONS:,}"
            }, 400

        if not self.try_acquire_cpu_work_slot():
            return {
                "error": "CPU work capacity is busy; retry later",
                "retryable": True,
            }, 429

        try:
            start_time = time.time()

            # Perform CPU-intensive work (blocking)
            result = 0.0
            for i in range(iterations):
                result += math.sqrt(i + 1) * math.sin(i)
                result = result % 1_000_000  # Prevent overflow

            duration_ms = (time.time() - start_time) * 1000.0
        finally:
            self.release_cpu_work_slot()

        # Get pod name for visibility into load distribution
        pod_name = os.environ.get("HOSTNAME", "unknown")

        return {
            "status": "completed",
            "iterations": iterations,
            "duration_ms": round(duration_ms, 2),
            "result": round(result, 4),
            "pod_name": pod_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, 200

    @swag_from(CPU_LOAD_WORK_SPEC)
    def cpu_load_work(self):
        """
        Synchronous CPU work endpoint for distributed load testing.

        Unlike /load/cpu which starts background workers and returns immediately,
        this endpoint blocks until the work is complete. This allows external load
        generators (hey, k6, wrk) to distribute requests across pods via the
        Kubernetes Service load balancer.
        """
        data = request.get_json() or {}
        body, status = self.run_cpu_work(
            data.get("iterations", CPU_WORK_DEFAULT_ITERATIONS)
        )
        return jsonify(body), status
