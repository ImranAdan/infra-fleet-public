"""Base worker abstraction for load generation.

Provides abstract base classes for implementing load workers following
the Template Method and Strategy patterns. This eliminates code duplication
between CPU and Memory workers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import time
import uuid


@dataclass
class JobConfig:
    """Base configuration for a load test job.

    All job types extend this with their specific parameters.
    """

    duration_seconds: float
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        return {
            "job_id": self.job_id,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class JobStatus:
    """Status information for a running or completed job."""

    job_id: str
    status: str  # "running", "completed", "stopped", "failed"
    started_at: str
    config: Dict[str, Any]
    completed_at: Optional[str] = None
    stopped_at: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def running(cls, job_id: str, config: Dict[str, Any]) -> "JobStatus":
        """Create a running job status."""
        return cls(
            job_id=job_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            config=config,
        )

    def mark_completed(self) -> None:
        """Mark the job as completed."""
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_stopped(self) -> None:
        """Mark the job as stopped (manually terminated)."""
        self.status = "stopped"
        self.stopped_at = datetime.now(timezone.utc).isoformat()

    def mark_failed(self, error: str) -> None:
        """Mark the job as failed with an error message."""
        self.status = "failed"
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert status to dictionary for JSON serialization."""
        result = {
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at,
            "config": self.config,
        }
        if self.completed_at:
            result["completed_at"] = self.completed_at
        if self.stopped_at:
            result["stopped_at"] = self.stopped_at
        if self.error:
            result["error"] = self.error
        return result


class BaseWorker(ABC):
    """Abstract base class for load test workers.

    Implements the Template Method pattern for worker lifecycle:
    1. validate_config() - Parse and validate input
    2. execute() - Run the actual workload (in subprocess)

    Subclasses implement the specific workload logic.
    """

    @property
    @abstractmethod
    def worker_type(self) -> str:
        """Return the worker type identifier (e.g., 'cpu', 'memory')."""
        pass

    @property
    @abstractmethod
    def job_prefix(self) -> str:
        """Return the prefix for job IDs (e.g., 'job_', 'mem_')."""
        pass

    @abstractmethod
    def validate_config(self, data: Dict[str, Any]) -> JobConfig:
        """Validate input data and return a typed config object.

        Args:
            data: Raw input data from request

        Returns:
            Validated JobConfig subclass instance

        Raises:
            ValueError: If validation fails
        """
        pass

    @abstractmethod
    def execute(self, config: JobConfig, stop_event) -> Dict[str, Any]:
        """Execute the load test workload.

        This method runs in a separate process and should be CPU/memory
        intensive as appropriate. It should check stop_event periodically
        to support graceful termination.

        Args:
            config: Validated job configuration
            stop_event: multiprocessing.Event to signal early termination

        Returns:
            Dictionary with execution results
        """
        pass

    def generate_job_id(self) -> str:
        """Generate a unique job ID with the appropriate prefix."""
        timestamp = int(time.time() * 1000)
        return f"{self.job_prefix}{timestamp}"
