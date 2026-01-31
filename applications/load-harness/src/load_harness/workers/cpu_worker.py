"""CPU load worker implementation.

Generates CPU-intensive workload by performing mathematical operations.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict

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
    CPU_JOB_PREFIX,
)
from load_harness.workers.base import BaseWorker, JobConfig


@dataclass
class CPUJobConfig(JobConfig):
    """Configuration for a CPU load job."""

    cores: int = CPU_DEFAULT_CORES
    intensity: int = CPU_DEFAULT_INTENSITY

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        base = super().to_dict()
        base.update({
            "cores": self.cores,
            "intensity": self.intensity,
        })
        return base


class CPUWorker(BaseWorker):
    """CPU load generation worker.

    Creates CPU-intensive workload by performing mathematical operations
    (sqrt, sin, modulo) in a tight loop. The intensity parameter controls
    how many operations per iteration, affecting CPU pressure.
    """

    def __init__(self, available_cores: int = 16):
        """Initialize CPU worker.

        Args:
            available_cores: Maximum cores available (from cgroup or system)
        """
        self.available_cores = available_cores

    @property
    def worker_type(self) -> str:
        return "cpu"

    @property
    def job_prefix(self) -> str:
        return CPU_JOB_PREFIX

    def validate_config(self, data: Dict[str, Any]) -> CPUJobConfig:
        """Validate CPU load configuration.

        Args:
            data: Request data with cores, duration_seconds, intensity

        Returns:
            Validated CPUJobConfig

        Raises:
            ValueError: If any parameter is invalid
        """
        cores = data.get("cores", CPU_DEFAULT_CORES)
        duration_seconds = data.get("duration_seconds", CPU_DEFAULT_DURATION_SECONDS)
        intensity = data.get("intensity", CPU_DEFAULT_INTENSITY)

        # Validate cores
        if not isinstance(cores, int):
            raise ValueError("cores must be an integer")
        if cores < CPU_MIN_CORES or cores > CPU_MAX_CORES:
            raise ValueError(f"cores must be between {CPU_MIN_CORES} and {CPU_MAX_CORES}")
        if cores > self.available_cores:
            raise ValueError(
                f"cores ({cores}) exceeds available cores ({self.available_cores})"
            )

        # Validate duration
        if not isinstance(duration_seconds, (int, float)):
            raise ValueError("duration_seconds must be a number")
        if duration_seconds < CPU_MIN_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be at least {CPU_MIN_DURATION_SECONDS}"
            )
        if duration_seconds > CPU_MAX_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be at most {CPU_MAX_DURATION_SECONDS}"
            )

        # Validate intensity
        if not isinstance(intensity, int):
            raise ValueError("intensity must be an integer")
        if intensity < CPU_MIN_INTENSITY or intensity > CPU_MAX_INTENSITY:
            raise ValueError(
                f"intensity must be between {CPU_MIN_INTENSITY} and {CPU_MAX_INTENSITY}"
            )

        return CPUJobConfig(
            job_id=self.generate_job_id(),
            duration_seconds=duration_seconds,
            cores=cores,
            intensity=intensity,
        )

    def execute(self, config: CPUJobConfig, stop_event) -> Dict[str, Any]:
        """Execute CPU-intensive workload.

        Runs in a separate process, performing mathematical operations
        until duration expires or stop_event is set.

        Args:
            config: Validated CPU job configuration
            stop_event: Event to signal early termination

        Returns:
            Dictionary with execution results
        """
        start_time = time.time()
        end_time = start_time + config.duration_seconds
        iterations = 0
        result = 0.0

        # CPU-intensive loop
        while time.time() < end_time:
            # Check for early termination
            if stop_event.is_set():
                break

            # Perform CPU-intensive work
            # intensity controls how many operations per check
            for _ in range(config.intensity * 1000):
                result += math.sqrt(iterations + 1) * math.sin(iterations)
                result = result % 1_000_000  # Prevent overflow
                iterations += 1

        actual_duration = time.time() - start_time

        return {
            "job_id": config.job_id,
            "iterations": iterations,
            "duration_seconds": round(actual_duration, 2),
            "intensity": config.intensity,
            "result": round(result, 4),
        }


def cpu_worker_target(
    worker_id: str,
    duration_seconds: float,
    complexity: int,
    stop_event,
) -> Dict[str, Any]:
    """Standalone worker function for multiprocessing.

    This function is pickle-able and can be used as the target for
    multiprocessing.Process. It wraps the CPUWorker.execute() method.

    Args:
        worker_id: Unique identifier for this worker instance
        duration_seconds: How long to run
        complexity: Intensity level (1-10)
        stop_event: multiprocessing.Event for termination

    Returns:
        Execution results dictionary
    """
    start_time = time.time()
    end_time = start_time + duration_seconds
    iterations = 0
    result = 0.0

    while time.time() < end_time:
        if stop_event.is_set():
            break

        for _ in range(complexity * 1000):
            result += math.sqrt(iterations + 1) * math.sin(iterations)
            result = result % 1_000_000
            iterations += 1

    return {
        "worker_id": worker_id,
        "iterations": iterations,
        "duration_seconds": time.time() - start_time,
    }
