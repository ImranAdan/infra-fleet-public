"""Pod-wide memory reservations shared by all Gunicorn worker processes."""

import fcntl
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional


class MemoryBudget:
    """Atomically reserve a cgroup-derived memory budget across web workers.

    Gunicorn workers do not share Python objects. A small file-backed ledger and
    advisory lock coordinate the processes in the one application container.
    Kubernetes pods have separate filesystems, so the scope is exactly one pod.
    """

    def __init__(self, limit_mb: int, directory: Optional[str] = None):
        self.limit_mb = int(limit_mb)
        configured = directory or os.getenv(
            "MEMORY_RESERVATION_DIRECTORY", "/tmp/load-harness-memory"
        )
        self.directory = Path(configured)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock_path = self.directory / "reservations.lock"
        self.state_path = self.directory / "reservations.json"

    @staticmethod
    def _pid_is_alive(pid) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _read(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            with self.state_path.open(encoding="utf-8") as state_file:
                state = json.load(state_file)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Memory reservation state is unreadable") from error
        if not isinstance(state, dict):
            raise RuntimeError("Memory reservation state has an invalid shape")
        return state

    def _write(self, state: dict) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.directory, prefix="reservations.", suffix=".tmp"
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
                json.dump(state, state_file, sort_keys=True)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_name, self.state_path)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _open_lock(self):
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        lock_file = os.fdopen(descriptor, "r+")
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return lock_file

    def _prune(self, state: dict) -> None:
        stale = []
        for reservation_id, reservation in state.items():
            if not isinstance(reservation, dict):
                stale.append(reservation_id)
                continue
            worker_pid = reservation.get("worker_pid")
            owner_pid = reservation.get("owner_pid")
            active_pid = worker_pid if worker_pid is not None else owner_pid
            if not self._pid_is_alive(active_pid):
                stale.append(reservation_id)
        for reservation_id in stale:
            state.pop(reservation_id, None)

    def reserve(self, size_mb: int) -> Optional[str]:
        """Reserve capacity, returning an opaque ID or None when exhausted."""
        size_mb = int(size_mb)
        lock_file = self._open_lock()
        try:
            state = self._read()
            self._prune(state)
            allocated = sum(int(item.get("size_mb", 0)) for item in state.values())
            if size_mb <= 0 or allocated + size_mb > self.limit_mb:
                self._write(state)
                return None
            reservation_id = uuid.uuid4().hex
            state[reservation_id] = {
                "size_mb": size_mb,
                "owner_pid": os.getpid(),
                "worker_pid": None,
            }
            self._write(state)
            return reservation_id
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

    def activate(self, reservation_id: str, worker_pid: int) -> None:
        """Bind a reservation to the child process holding the memory."""
        lock_file = self._open_lock()
        try:
            state = self._read()
            reservation = state.get(reservation_id)
            if not reservation:
                raise RuntimeError("Memory reservation disappeared before activation")
            reservation["worker_pid"] = int(worker_pid)
            self._write(state)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

    def release(self, reservation_id: Optional[str]) -> None:
        """Release a reservation. Repeated releases are safe."""
        if not reservation_id:
            return
        lock_file = self._open_lock()
        try:
            state = self._read()
            state.pop(reservation_id, None)
            self._prune(state)
            self._write(state)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
