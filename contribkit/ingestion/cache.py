import hashlib
import json
import time
from functools import wraps
from pathlib import Path

_bypass = False


def set_bypass(value: bool) -> None:
    global _bypass
    _bypass = value


def _key(*args, **kwargs) -> str:
    payload = json.dumps([args, sorted(kwargs.items())], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


class _DiskCache:
    def __init__(self, path: Path, ttl: int):
        self.path = path
        self.ttl = ttl
        self._data: dict = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def get(self, key: str):
        entry = self._data.get(key)
        if entry and (time.time() - entry["ts"]) < self.ttl:
            return entry["v"]
        return None

    def set(self, key: str, value) -> None:
        self._data[key] = {"ts": time.time(), "v": value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data), encoding="utf-8")


def cached(fetch_type: str):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            if _bypass:
                return await fn(*args, **kwargs)
            from contribkit.config import get_settings
            s = get_settings()
            cache = _DiskCache(Path(s.cache_dir) / "cache.json", s.cache_ttl)
            key = f"{fetch_type}:{_key(*args, **kwargs)}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = await fn(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator
