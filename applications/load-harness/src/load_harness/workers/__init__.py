"""Worker module for load generation.

Workers run in separate processes to keep the Flask process responsive.
Validation lives with the endpoints in load_harness_service; these are the
process targets only.
"""

from load_harness.workers.cpu_worker import cpu_worker_target
from load_harness.workers.memory_worker import memory_worker_target

__all__ = [
    "cpu_worker_target",
    "memory_worker_target",
]
