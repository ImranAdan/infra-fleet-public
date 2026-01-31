"""Memory load worker implementation.

Generates memory-intensive workload by allocating and holding memory.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict

from load_harness.constants import (
    MEMORY_MAX_SIZE_MB,
    MEMORY_MIN_SIZE_MB,
    MEMORY_DEFAULT_SIZE_MB,
    MEMORY_MAX_DURATION_SECONDS,
    MEMORY_MIN_DURATION_SECONDS,
    MEMORY_DEFAULT_DURATION_SECONDS,
    MEMORY_PAGE_SIZE_BYTES,
    MEMORY_JOB_PREFIX,
)
from load_harness.workers.base import BaseWorker, JobConfig


@dataclass
class MemoryJobConfig(JobConfig):
    """Configuration for a memory load job."""

    size_mb: int = MEMORY_DEFAULT_SIZE_MB

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        base = super().to_dict()
        base.update({
            "size_mb": self.size_mb,
        })
        return base


class MemoryWorker(BaseWorker):
    """Memory load generation worker.

    Allocates a specified amount of memory, touches all pages to ensure
    physical allocation, and holds the memory for the specified duration.
    """

    @property
    def worker_type(self) -> str:
        return "memory"

    @property
    def job_prefix(self) -> str:
        return MEMORY_JOB_PREFIX

    def validate_config(self, data: Dict[str, Any]) -> MemoryJobConfig:
        """Validate memory load configuration.

        Args:
            data: Request data with size_mb, duration_seconds

        Returns:
            Validated MemoryJobConfig

        Raises:
            ValueError: If any parameter is invalid
        """
        size_mb = data.get("size_mb", MEMORY_DEFAULT_SIZE_MB)
        duration_seconds = data.get("duration_seconds", MEMORY_DEFAULT_DURATION_SECONDS)

        # Validate size
        if not isinstance(size_mb, (int, float)):
            raise ValueError("size_mb must be a number")
        if size_mb < MEMORY_MIN_SIZE_MB or size_mb > MEMORY_MAX_SIZE_MB:
            raise ValueError(
                f"size_mb must be between {MEMORY_MIN_SIZE_MB} and {MEMORY_MAX_SIZE_MB}"
            )

        # Validate duration
        if not isinstance(duration_seconds, (int, float)):
            raise ValueError("duration_seconds must be a number")
        if duration_seconds < MEMORY_MIN_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be at least {MEMORY_MIN_DURATION_SECONDS}"
            )
        if duration_seconds > MEMORY_MAX_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be at most {MEMORY_MAX_DURATION_SECONDS}"
            )

        return MemoryJobConfig(
            job_id=self.generate_job_id(),
            duration_seconds=duration_seconds,
            size_mb=int(size_mb),
        )

    def execute(self, config: MemoryJobConfig, stop_event) -> Dict[str, Any]:
        """Execute memory allocation workload.

        Allocates memory, touches all pages, holds for duration, then releases.

        Args:
            config: Validated memory job configuration
            stop_event: Event to signal early termination

        Returns:
            Dictionary with execution results
        """
        start_time = time.time()
        end_time = start_time + config.duration_seconds

        # Allocate memory
        bytes_to_allocate = config.size_mb * 1024 * 1024
        memory_block = bytearray(bytes_to_allocate)

        # Touch all pages to ensure physical allocation
        for i in range(0, len(memory_block), MEMORY_PAGE_SIZE_BYTES):
            memory_block[i] = i % 256

        allocation_time = time.time() - start_time

        # Hold memory until duration expires or stop signal
        while time.time() < end_time:
            if stop_event.is_set():
                break
            time.sleep(0.1)  # Check every 100ms

        actual_duration = time.time() - start_time

        # Memory is released when function returns
        return {
            "job_id": config.job_id,
            "size_mb": config.size_mb,
            "bytes_allocated": bytes_to_allocate,
            "allocation_time_seconds": round(allocation_time, 3),
            "actual_duration_seconds": round(actual_duration, 2),
        }


def memory_worker_target(
    job_id: str,
    size_mb: int,
    duration_seconds: float,
    stop_event,
) -> Dict[str, Any]:
    """Standalone worker function for multiprocessing.

    This function is pickle-able and can be used as the target for
    multiprocessing.Process. It wraps the MemoryWorker.execute() method.

    Args:
        job_id: Unique identifier for this job
        size_mb: Amount of memory to allocate
        duration_seconds: How long to hold the memory
        stop_event: multiprocessing.Event for termination

    Returns:
        Execution results dictionary
    """
    start_time = time.time()
    end_time = start_time + duration_seconds

    # Allocate memory
    bytes_to_allocate = int(size_mb * 1024 * 1024)
    memory_block = bytearray(bytes_to_allocate)

    # Touch all pages
    for i in range(0, len(memory_block), MEMORY_PAGE_SIZE_BYTES):
        memory_block[i] = i % 256

    allocation_time = time.time() - start_time

    # Hold memory
    while time.time() < end_time:
        if stop_event.is_set():
            break
        time.sleep(0.1)

    return {
        "job_id": job_id,
        "size_mb": size_mb,
        "allocation_time_seconds": allocation_time,
        "actual_duration_seconds": time.time() - start_time,
    }
