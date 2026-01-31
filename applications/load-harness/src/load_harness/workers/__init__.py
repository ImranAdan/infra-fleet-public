"""Worker module for load generation.

This module provides worker abstractions for CPU and memory load generation.
Workers run in separate processes to keep the main Flask process responsive.
"""

from load_harness.workers.base import BaseWorker, JobConfig, JobStatus
from load_harness.workers.cpu_worker import CPUWorker, CPUJobConfig
from load_harness.workers.memory_worker import MemoryWorker, MemoryJobConfig

__all__ = [
    "BaseWorker",
    "JobConfig",
    "JobStatus",
    "CPUWorker",
    "CPUJobConfig",
    "MemoryWorker",
    "MemoryJobConfig",
]
