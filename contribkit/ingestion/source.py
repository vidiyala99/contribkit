from pathlib import Path

_SKIP = {"__pycache__", ".venv", "venv", "node_modules", ".git", "dist", "build"}


def read_source_files(path: str, max_bytes: int = 200_000) -> tuple[str, list[str]]:
    root = Path(path)
    parts: list[str] = []
    excluded: list[str] = []
    total = 0
    for f in sorted(root.rglob("*.py")):
        if any(p in f.parts for p in _SKIP):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        chunk = f"### {f.relative_to(root)}\n```python\n{content}\n```"
        if total + len(chunk.encode()) > max_bytes:
            excluded.append(str(f.relative_to(root)))
            continue
        parts.append(chunk)
        total += len(chunk.encode())
    return "\n\n".join(parts), excluded
