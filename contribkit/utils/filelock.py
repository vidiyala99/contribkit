import contextlib
from pathlib import Path


@contextlib.contextmanager
def file_lock(path: Path):
    """Cross-platform exclusive file lock. Blocks until the lock is acquired."""
    lock_path = path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "w")
    try:
        try:
            import fcntl
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            yield
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            yield
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        lock_file.close()
