"""Memory load worker.

Runs in a separate process (spawn context) so the allocation is charged to
a child process and released when it exits.
"""

import time
from typing import Any, Dict

from load_harness.constants import MEMORY_PAGE_SIZE_BYTES


def memory_worker_target(
    job_id: str,
    size_mb: int,
    duration_seconds: float,
    stop_event,
) -> Dict[str, Any]:
    """Allocate memory, touch every page, and hold it for the duration.

    Must stay importable at module level: multiprocessing's spawn context
    pickles the target by reference.

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

    bytes_to_allocate = int(size_mb * 1024 * 1024)
    memory_block = bytearray(bytes_to_allocate)

    # Touch every page so the allocation is resident, not just reserved.
    for i in range(0, len(memory_block), MEMORY_PAGE_SIZE_BYTES):
        memory_block[i] = i % 256

    allocation_time = time.time() - start_time

    while time.time() < end_time:
        if stop_event.is_set():
            break
        time.sleep(0.1)

    return {
        "job_id": job_id,
        "size_mb": size_mb,
        "bytes_allocated": bytes_to_allocate,
        "allocation_time_seconds": allocation_time,
        "actual_duration_seconds": time.time() - start_time,
    }
