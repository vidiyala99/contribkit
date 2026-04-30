import hashlib
import json
import time
from functools import wraps
from pathlib import Path

from contribkit.utils.filelock import file_lock
from contribkit.utils.validation import slug_to_filename

_bypass = False


def set_bypass(value: bool) -> None:
    global _bypass
    _bypass = value


def _key(*args, **kwargs) -> str:
    payload = json.dumps([args, sorted(kwargs.items())], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _repo_shard(cache_dir: str, repo: str) -> Path:
    return Path(cache_dir) / "cache" / f"{slug_to_filename(repo)}.json"


class _DiskCache:
    def __init__(self, path: Path, ttl: int):
        self.path = path
        self.ttl = ttl

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def get(self, key: str):
        with file_lock(self.path):
            data = self._load()
        entry = data.get(key)
        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["v"]
        return None

    def set(self, key: str, value) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            data = self._load()
            data[key] = {"ts": time.time(), "v": value}
            self.path.write_text(json.dumps(data), encoding="utf-8")


def cached(fetch_type: str):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            if _bypass:
                return await fn(*args, **kwargs)
            from contribkit.config import get_settings
            s = get_settings()
            # Infer repo from first positional arg (always the repo slug)
            repo = args[0] if args else "default"
            shard = _repo_shard(s.cache_dir, repo)
            cache = _DiskCache(shard, s.cache_ttl)
            key = f"{fetch_type}:{_key(*args, **kwargs)}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = await fn(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator


def clear(repo: str | None = None) -> list[str]:
    """Delete cache shard(s). Returns list of deleted file paths."""
    from contribkit.config import get_settings
    cache_root = Path(get_settings().cache_dir) / "cache"
    deleted = []
    if repo:
        shard = _repo_shard(get_settings().cache_dir, repo)
        if shard.exists():
            shard.unlink()
            deleted.append(str(shard))
        lock = shard.with_suffix(".lock")
        if lock.exists():
            lock.unlink()
    else:
        for f in cache_root.glob("*.json"):
            f.unlink()
            deleted.append(str(f))
        for f in cache_root.glob("*.lock"):
            f.unlink()
    return deleted
