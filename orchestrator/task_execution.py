"""Physical-execution exclusion that survives the task owner's death.

Acquire before loading/recovering a Driver, not merely before spawning a CLI:
Driver recovery can restore files. Workers inherit the lease descriptor, while
the durable dispatch journal also protects against workers closing unknown FDs.
Neither acquiring nor releasing a lease signals an existing worker.
"""

import errno
import fcntl
import json
import os
import tempfile
import time


class ExecutionBusy(RuntimeError):
    """Another owner or a not-yet-quiescent physical attempt excludes recovery."""


class TaskExecutionLease:
    def __init__(self, task_dir, on_pending=None, poll_interval=0.1):
        self.task_dir = os.path.abspath(os.fspath(task_dir))
        self.lock_path = os.path.join(self.task_dir, "execution.lock")
        self.journal_path = os.path.join(self.task_dir, "execution.json")
        self._fd = None
        self.on_pending = on_pending
        self.poll_interval = poll_interval

    def acquire(self):
        if self._fd is not None:
            raise RuntimeError("execution lease is already acquired")
        os.makedirs(self.task_dir, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise ExecutionBusy(
                        "task execution is still owned by another process "
                        "or a surviving worker"
                    ) from exc
                raise
            self._fd = fd
            self._ensure_quiescent()
            return self
        except BaseException:
            self._fd = None
            os.close(fd)
            raise

    def close(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            # LOCK_UN would unlock the shared open-file description in the
            # child too. Closing ONLY our reference leaves a surviving worker
            # holding the lock until its last inherited descriptor is closed.
            os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.close()

    def _require_acquired(self):
        if self._fd is None:
            raise RuntimeError("execution lease is not acquired")

    def _read(self):
        try:
            with open(self.journal_path, encoding="utf-8") as handle:
                value = json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ExecutionBusy(
                "cannot establish worker quiescence: unreadable execution journal"
            ) from exc
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ExecutionBusy("cannot establish worker quiescence: invalid execution journal")
        return value

    def _write(self, value):
        fd, temporary = tempfile.mkstemp(prefix=".execution-", dir=self.task_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.journal_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _clear(self):
        try:
            os.unlink(self.journal_path)
        except FileNotFoundError:
            pass

    def _ensure_quiescent(self):
        self._require_acquired()
        state = self._read()
        if state is None:
            return
        pgid = state.get("pgid")
        if state.get("phase") != "worker" or type(pgid) is not int or pgid <= 0:
            raise ExecutionBusy(
                "dispatch was interrupted before worker identity was recorded; "
                "cannot establish quiescence, so recovery is blocked"
            )
        # Inspect the whole group, including children whose leader has exited.
        # Identifier reuse is conservative: it may delay recovery, never kill
        # or mistake an unrelated live group for a safe-to-retry attempt.
        from .runners import _process_group_quiescent
        if _process_group_quiescent(pgid) is not True:
            raise ExecutionBusy(
                "prior worker process group %d is still active or its "
                "quiescence cannot be established" % pgid
            )
        self._clear()

    def prepare_spawn(self, popen_kwargs):
        """Journal before dispatch and inherit the lock through either transport."""
        self._ensure_quiescent()
        popen_kwargs["pass_fds"] = tuple(sorted(set(
            tuple(popen_kwargs.get("pass_fds", ())) + (self._fd,)
        )))
        self._write({"version": 1, "phase": "dispatching"})

    def record_worker(self, pid):
        self._require_acquired()
        if type(pid) is not int or pid <= 0:
            raise RuntimeError("worker has no valid process group identity")
        # SubprocessRunner always starts a new session: pgid equals pid even
        # if the leader exits before this write, leaving live descendants.
        self._write({"version": 1, "phase": "worker", "pgid": pid})

    def finish_spawn(self, worker_quiescent):
        self._require_acquired()
        if worker_quiescent is True:
            self._clear()
            return
        if self.on_pending is not None:
            # Keep the outcome (or original exception) inside the transport
            # until it is safe for post-call callbacks to inspect/restore Git.
            # A durable Cancel does not waive this physical boundary.
            while True:
                try:
                    self.on_pending()
                    break
                except Exception:
                    # A transient control-store failure must not accidentally
                    # deliver an unsafe result through the exception path.
                    time.sleep(self.poll_interval)
            while True:
                try:
                    self._ensure_quiescent()
                    return
                except (ExecutionBusy, OSError):
                    time.sleep(self.poll_interval)

    def ensure_quiescent(self):
        """Check retained worker evidence while this coordinator owns the lease."""
        self._ensure_quiescent()
