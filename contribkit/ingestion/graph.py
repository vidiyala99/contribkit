"""Persistent codebase graph: one-time deep analysis stored as structured JSON."""

import json
import time
from pathlib import Path

import anthropic

from contribkit.config import get_settings
from contribkit.exceptions import LLMParseError
from contribkit.ingestion.source import read_source_files
from contribkit.synthesis.parsing import extract_tagged_json
from contribkit.utils.validation import slug_to_filename

_GRAPH_PROMPT = """\
You are a senior software architect performing a one-time deep analysis of a codebase.

Read the source files below and produce a structured knowledge graph of this codebase.
This graph will be used in future sessions to generate high-quality contribution proposals
without re-reading all source files.

## Source Files
{source}

Produce a JSON object with these fields:
- architecture_summary: 3-5 sentence overview of the system design and key patterns
- modules: array of {{name, path, purpose, key_functions}} for each significant module
- abstractions: array of {{name, type, description}} for key classes/interfaces/patterns
- patterns: array of {{name, description}} for recurring design patterns in the code
- pain_points: array of {{area, description}} for structural weaknesses or tech debt visible in code
- entry_points: array of file paths that are the main entry points to the system
- dependencies: array of {{name, purpose}} for key external packages used

Wrap the JSON in <graph>...</graph> tags. No other text outside the tags.
"""


def _graphs_dir() -> Path:
    return Path(get_settings().cache_dir) / "graphs"


def _graph_path(repo: str) -> Path:
    return _graphs_dir() / f"{slug_to_filename(repo)}.json"


def graph_exists(repo: str) -> bool:
    return _graph_path(repo).exists()


def load_graph(repo: str) -> dict | None:
    p = _graph_path(repo)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_graph(repo: str, graph: dict) -> None:
    p = _graph_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(graph, indent=2), encoding="utf-8")


def build_graph(repo: str, source_path: str) -> dict:
    """Run a one-time deep analysis of source_path and return a structured graph."""
    source, _ = read_source_files(source_path, get_settings().max_source_bytes)
    if not source.strip():
        raise ValueError(f"No Python source files found at {source_path!r}")

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=8192,
        messages=[{"role": "user", "content": _GRAPH_PROMPT.format(source=source)}],
    )

    raw = response.content[0].text
    data = extract_tagged_json(raw, "graph")
    if not isinstance(data, dict):
        raise LLMParseError(f"Expected a JSON object for graph, got {type(data).__name__}")

    graph = {
        "repo": repo,
        "source_path": source_path,
        "analyzed_at": time.time(),
        **data,
    }
    save_graph(repo, graph)
    return graph


def graph_to_focused_context(graph: dict, patterns: list[str]) -> str:
    """Like graph_to_context but narrows modules and pain_points to those matching focus patterns."""
    import fnmatch

    def _matches(text: str) -> bool:
        return any(fnmatch.fnmatch(text, pat) for pat in patterns)

    focused = dict(graph)
    if graph.get("modules"):
        filtered = [m for m in graph["modules"] if _matches(m.get("path", ""))]
        focused["modules"] = filtered or graph["modules"]  # fallback: all if nothing matched
    if graph.get("pain_points"):
        filtered = [pt for pt in graph["pain_points"] if _matches(pt.get("area", ""))]
        focused["pain_points"] = filtered or graph["pain_points"]
    return graph_to_context(focused)


def graph_to_context(graph: dict) -> str:
    """Serialize a graph to a compact prompt-ready string."""
    lines = [f"## Codebase Architecture ({graph.get('repo', 'unknown')})"]
    lines.append(graph.get("architecture_summary", ""))

    if graph.get("modules"):
        lines.append("\n### Modules")
        for m in graph["modules"]:
            lines.append(f"- **{m['name']}** (`{m.get('path','?')}`): {m.get('purpose','')}")
            if m.get("key_functions"):
                lines.append(f"  Functions: {', '.join(m['key_functions'])}")

    if graph.get("abstractions"):
        lines.append("\n### Key Abstractions")
        for a in graph["abstractions"]:
            lines.append(f"- **{a['name']}** ({a.get('type','?')}): {a.get('description','')}")

    if graph.get("patterns"):
        lines.append("\n### Design Patterns")
        for p in graph["patterns"]:
            lines.append(f"- **{p['name']}**: {p.get('description','')}")

    if graph.get("pain_points"):
        lines.append("\n### Pain Points / Tech Debt")
        for pt in graph["pain_points"]:
            lines.append(f"- **{pt['area']}**: {pt.get('description','')}")

    if graph.get("dependencies"):
        lines.append("\n### Key Dependencies")
        for d in graph["dependencies"]:
            lines.append(f"- {d['name']}: {d.get('purpose','')}")

    return "\n".join(lines)
