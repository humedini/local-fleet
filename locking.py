"""One lock for every process that writes Local Fleet's files (gateway, Desktop backend, `watch`,
CLI): an exclusive `flock` on `<data dir>/.lock`, re-entrant within a process so a transaction can
call code that also locks. Every writer reloads what is on disk inside the lock and saves before
releasing, so a probe never overwrites a rename made a moment earlier and a removed box never comes
back. Windows has no fcntl; there the lock covers threads of one process only.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

_thread_lock = threading.RLock()
_held: dict[str, list] = {}  # path -> [fd, depth]; only touched while _thread_lock is held


@contextmanager
def locked(data_dir: Path):
    path = str(Path(data_dir) / ".lock")
    with _thread_lock:
        entry = _held.get(path)
        if entry is None:
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            entry = _held[path] = [fd, 0]
        entry[1] += 1
        try:
            yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del _held[path]
                if fcntl is not None:
                    fcntl.flock(entry[0], fcntl.LOCK_UN)
                os.close(entry[0])
