"""Persistent proposal store — the RSI feedback loop's memory."""

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

from contribkit.config import get_settings

Status = Literal["open", "in_progress", "done", "dismissed"]


def _store_path(repo: str) -> Path:
    safe = repo.replace("/", "__")
    return Path(get_settings().cache_dir) / "proposals" / f"{safe}.json"


def _proposal_id(repo: str, title: str) -> str:
    return hashlib.sha256(f"{repo}:{title}".encode()).hexdigest()[:12]


def _load(repo: str) -> dict[str, dict]:
    p = _store_path(repo)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(repo: str, store: dict[str, dict]) -> None:
    p = _store_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2), encoding="utf-8")


def save_proposals(repo: str, proposals: list[dict], graph_analyzed_at: float | None = None) -> tuple[list[dict], list[dict]]:
    """Persist proposals. Returns (new, already_tracked)."""
    store = _load(repo)
    new, existing = [], []
    for p in proposals:
        pid = _proposal_id(repo, p["title"])
        if pid in store:
            existing.append({**store[pid], "_id": pid})
        else:
            entry = {
                "id": pid,
                "repo": repo,
                "title": p["title"],
                "problem": p["problem"],
                "approach": p["approach"],
                "files": p.get("files", []),
                "effort": p.get("effort", "medium"),
                "pr_title": p.get("pr_title", ""),
                "pr_body": p.get("pr_body", ""),
                "status": "open",
                "generated_at": time.time(),
                "graph_analyzed_at": graph_analyzed_at,
                "resolved_at": None,
            }
            store[pid] = entry
            new.append({**entry, "_id": pid})
    _save(repo, store)
    return new, existing


def list_proposals(repo: str, status: Status | None = None) -> list[dict]:
    store = _load(repo)
    items = [{"_id": k, **v} for k, v in store.items()]
    if status:
        items = [p for p in items if p["status"] == status]
    return sorted(items, key=lambda p: p["generated_at"])


def set_status(repo: str, proposal_id: str, status: Status) -> bool:
    store = _load(repo)
    if proposal_id not in store:
        return False
    store[proposal_id]["status"] = status
    if status in ("done", "dismissed"):
        store[proposal_id]["resolved_at"] = time.time()
    _save(repo, store)
    return True


def open_proposals_context(repo: str) -> str:
    """Compact summary of open proposals for injection into the analyze prompt."""
    open_props = list_proposals(repo, status="open")
    in_progress = list_proposals(repo, status="in_progress")
    all_active = open_props + in_progress
    if not all_active:
        return ""
    lines = ["## Already Proposed (do not re-propose these)"]
    for p in all_active:
        tag = "[in_progress]" if p["status"] == "in_progress" else "[open]"
        lines.append(f"- {tag} {p['title']} — {p['problem'][:120]}")
    return "\n".join(lines)
