"""Job manager service for tracking and managing load test jobs.

Replaces the global mutable state (_active_cpu_workers, _active_memory_workers)
with a proper service class that encapsulates job lifecycle management.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from multiprocessing import Event, Process
from typing import Any, Callable, Dict, List, Optional

from load_harness.constants import (
    JOB_CLEANUP_BUFFER_SECONDS,
    PROCESS_TERMINATE_TIMEOUT,
)


class JobManager:
    """Manages load test job lifecycle.

    Provides thread-safe tracking of running jobs, graceful termination,
    and automatic cleanup of completed jobs.

    This class replaces global module-level dictionaries with proper
    encapsulation and dependency injection.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize job manager.

        Args:
            logger: Optional logger instance. If not provided, creates one.
        """
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._logger = logger or logging.getLogger(self.__class__.__name__)

    def register_job(
        self,
        job_id: str,
        job_type: str,
        config: Dict[str, Any],
        processes: List[Process],
        stop_event: Event,
    ) -> None:
        """Register a new running job.

        Args:
            job_id: Unique job identifier
            job_type: Type of job ('cpu' or 'memory')
            config: Job configuration dictionary
            processes: List of worker processes
            stop_event: Event for signaling termination
        """
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "type": job_type,
                "config": config,
                "processes": processes,
                "stop_event": stop_event,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "running",
            }
        self._logger.info(
            "Registered job: job_id=%s type=%s", job_id, job_type
        )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job dictionary or None if not found
        """
        with self._lock:
            return self._jobs.get(job_id)

    def get_all_jobs(self, job_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all jobs, optionally filtered by type.

        Args:
            job_type: Optional filter by job type ('cpu' or 'memory')

        Returns:
            List of job status dictionaries (safe for JSON serialization)
        """
        with self._lock:
            jobs = []
            for job_id, job in self._jobs.items():
                if job_type and job.get("type") != job_type:
                    continue

                # Check process status
                processes = job.get("processes", [])
                active_count = sum(
                    1 for p in processes if p and p.is_alive()
                )

                # Build status dict (without non-serializable objects)
                status_dict = {
                    "job_id": job_id,
                    "type": job.get("type"),
                    "status": "running" if active_count > 0 else job.get("status", "completed"),
                    "config": job.get("config", {}),
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                    "stopped_at": job.get("stopped_at"),
                }

                # Add type-specific fields
                if job.get("type") == "cpu":
                    status_dict["cores_active"] = active_count
                    status_dict["cores_requested"] = job.get("config", {}).get("cores", 0)

                jobs.append(status_dict)

            return jobs

    def stop_job(self, job_id: str) -> bool:
        """Stop a specific job.

        Args:
            job_id: Job identifier

        Returns:
            True if job was stopped, False if not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            handles = self._detach(job)
            job["status"] = "stopped"
            job["stopped_at"] = datetime.now(timezone.utc).isoformat()

        self._reap(*handles)
        self._logger.info("Stopped job: job_id=%s", job_id)
        return True

    def stop_all_jobs(self, job_type: Optional[str] = None) -> List[str]:
        """Stop all jobs, optionally filtered by type.

        Args:
            job_type: Optional filter by job type

        Returns:
            List of stopped job IDs
        """
        stopped = []
        detached = []
        with self._lock:
            for job_id, job in self._jobs.items():
                if job_type and job.get("type") != job_type:
                    continue
                if job.get("status") == "running":
                    detached.append(self._detach(job))
                    job["status"] = "stopped"
                    job["stopped_at"] = datetime.now(timezone.utc).isoformat()
                    stopped.append(job_id)

        for handles in detached:
            self._reap(*handles)

        for job_id in stopped:
            self._logger.info("Stopped job: job_id=%s", job_id)

        return stopped

    @staticmethod
    def _detach(job: Dict[str, Any]):
        """Take the process handles off a job so they can be reaped unlocked.

        Must be called with the lock held. Also leaves the job dictionary
        JSON-serializable, which get_all_jobs relies on.

        Args:
            job: Job dictionary with processes and stop_event

        Returns:
            (processes, stop_event) for the caller to pass to _reap
        """
        return job.pop("processes", None) or [], job.pop("stop_event", None)

    @staticmethod
    def _reap(processes: List[Process], stop_event) -> None:
        """Signal, terminate and join worker processes.

        Must NOT be called with the lock held. Terminating a process can take
        up to two PROCESS_TERMINATE_TIMEOUT waits, and a CPU job holds one
        process per core - doing that under the lock blocked every status poll
        and every new job for the duration.

        Args:
            processes: Worker process handles, already detached from the job
            stop_event: Event the workers poll, or None
        """
        if stop_event:
            stop_event.set()

        for process in processes:
            if not process:
                continue
            if process.is_alive():
                process.terminate()
            process.join(timeout=PROCESS_TERMINATE_TIMEOUT)
            if process.is_alive():
                process.kill()
                process.join(timeout=PROCESS_TERMINATE_TIMEOUT)
            if not process.is_alive():
                process.close()

    def schedule_cleanup(
        self,
        job_id: str,
        duration_seconds: float,
        callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """Schedule automatic cleanup of a job after duration expires.

        Starts a daemon thread that waits for the job to complete and
        then cleans up resources.

        Args:
            job_id: Job identifier
            duration_seconds: Expected job duration
            callback: Optional callback to invoke after cleanup
        """
        cleanup_thread = threading.Thread(
            target=self._cleanup_job,
            args=(job_id, duration_seconds + JOB_CLEANUP_BUFFER_SECONDS, callback),
            daemon=True,
        )
        cleanup_thread.start()

    def _cleanup_job(
        self,
        job_id: str,
        wait_seconds: float,
        callback: Optional[Callable[[], None]],
    ) -> None:
        """Background cleanup of completed job.

        Args:
            job_id: Job identifier
            wait_seconds: How long to wait before cleanup
            callback: Optional callback to invoke
        """
        time.sleep(wait_seconds)

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return

            handles = self._detach(job)

            # Update status if still running
            if job.get("status") == "running":
                job["status"] = "completed"
                job["completed_at"] = datetime.now(timezone.utc).isoformat()

        self._reap(*handles)

        # Nothing else calls this, so finished jobs would accumulate for the
        # life of the process and lengthen every locked get_all_jobs scan.
        self.clear_completed()

        self._logger.debug("Cleaned up job: job_id=%s", job_id)

        if callback:
            callback()

    def get_active_count(self, job_type: Optional[str] = None) -> int:
        """Get count of currently running jobs.

        Args:
            job_type: Optional filter by job type

        Returns:
            Number of active jobs
        """
        jobs = self.get_all_jobs(job_type)
        return sum(1 for j in jobs if j.get("status") == "running")

    def clear_completed(self, max_age_seconds: float = 300) -> int:
        """Remove completed jobs older than max_age.

        Args:
            max_age_seconds: Maximum age of completed jobs to keep

        Returns:
            Number of jobs removed
        """
        removed = 0
        now = datetime.now(timezone.utc)

        with self._lock:
            jobs_to_remove = []
            for job_id, job in self._jobs.items():
                if job.get("status") in ("completed", "stopped"):
                    completed_at = job.get("completed_at") or job.get("stopped_at")
                    if completed_at:
                        try:
                            completed_time = datetime.fromisoformat(
                                completed_at.replace("Z", "+00:00")
                            )
                            age = (now - completed_time).total_seconds()
                            if age > max_age_seconds:
                                jobs_to_remove.append(job_id)
                        except (ValueError, TypeError):
                            pass

            for job_id in jobs_to_remove:
                del self._jobs[job_id]
                removed += 1

        return removed
