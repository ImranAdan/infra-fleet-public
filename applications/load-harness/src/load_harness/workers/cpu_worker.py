"""CPU load worker.

Runs in a separate process (spawn context) so the Flask workers stay
responsive while synthetic load is generated.
"""

import math
import time
from typing import Any, Dict


def cpu_worker_target(
    worker_id: str,
    duration_seconds: float,
    complexity: int,
    stop_event,
) -> Dict[str, Any]:
    """Burn CPU until the duration expires or the stop event is set.

    Must stay importable at module level: multiprocessing's spawn context
    pickles the target by reference.

    Args:
        worker_id: Unique identifier for this worker instance
        duration_seconds: How long to run
        complexity: Intensity level (1-10), scales work done between stop checks
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
