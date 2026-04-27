from pathlib import Path

_SKIP = {"__pycache__", ".venv", "venv", "node_modules", ".git", "dist", "build"}


def read_source_files(path: str) -> str:
    root = Path(path)
    parts = []
    for f in sorted(root.rglob("*.py")):
        if any(p in f.parts for p in _SKIP):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            parts.append(f"### {f.relative_to(root)}\n```python\n{content}\n```")
        except Exception:
            continue
    return "\n\n".join(parts)
