import asyncio
import re
import httpx
from contribkit.config import get_settings
from contribkit.exceptions import GitHubAPIError, RateLimitError, RepoNotFoundError
from contribkit.ingestion.cache import cached

_BASE = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_status(r: httpx.Response, repo: str = "") -> None:
    if r.status_code == 401:
        raise GitHubAPIError("GitHub authentication failed — check your GITHUB_TOKEN in .env")
    if r.status_code == 404:
        raise RepoNotFoundError(f"Repository '{repo}' not found — check the slug and your token permissions")
    if r.status_code in (403, 429):
        reset = r.headers.get("x-ratelimit-reset")
        hint = f" (resets at epoch {reset})" if reset else ""
        raise RateLimitError(f"GitHub rate limit exceeded{hint}")
    if r.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {r.status_code}: {r.text[:200]}")


def _next_url(link_header: str | None) -> str | None:
    if not link_header:
        return None
    match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    return match.group(1) if match else None


async def _paginate(client: httpx.AsyncClient, url: str, params: dict, repo: str = "", max_pages: int = 5) -> list:
    items = []
    current_url = url
    current_params: dict | None = params
    for _ in range(max_pages):
        r = await client.get(current_url, headers=_headers(), params=current_params)
        _raise_for_status(r, repo)
        items.extend(r.json())
        next_url = _next_url(r.headers.get("link"))
        if not next_url:
            break
        current_url = next_url
        current_params = None  # next URL already has params encoded
    return items


@cached("repo_info")
async def fetch_repo_info(repo: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_BASE}/repos/{repo}", headers=_headers())
        _raise_for_status(r, repo)
        d = r.json()
        return {
            "name": d["name"],
            "description": d["description"],
            "stars": d["stargazers_count"],
            "forks": d["forks_count"],
            "language": d["language"],
            "topics": d["topics"],
            "open_issues_count": d["open_issues_count"],
        }


@cached("issues")
async def fetch_issues(repo: str, limit: int = 50) -> list[dict]:
    max_pages = get_settings().github_max_pages
    async with httpx.AsyncClient() as client:
        raw = await _paginate(
            client,
            f"{_BASE}/repos/{repo}/issues",
            params={"state": "open", "per_page": 100, "sort": "updated"},
            repo=repo,
            max_pages=max_pages,
        )
    return [
        {
            "number": i["number"],
            "title": i["title"],
            "body": (i["body"] or "")[:1200],
            "labels": [l["name"] for l in i["labels"]],
            "comments": i["comments"],
            "reactions": i.get("reactions", {}).get("+1", 0),
            "created_at": i["created_at"],
            "url": i["html_url"],
        }
        for i in raw
        if "pull_request" not in i
    ][:limit]


@cached("prs")
async def fetch_prs(repo: str, state: str = "closed", limit: int = 30) -> list[dict]:
    max_pages = get_settings().github_max_pages
    async with httpx.AsyncClient() as client:
        raw = await _paginate(
            client,
            f"{_BASE}/repos/{repo}/pulls",
            params={"state": state, "per_page": 100, "sort": "updated"},
            repo=repo,
            max_pages=max_pages,
        )
    return [
        {
            "number": p["number"],
            "title": p["title"],
            "body": (p["body"] or "")[:600],
            "state": p["state"],
            "merged_at": p.get("merged_at"),
            "url": p["html_url"],
        }
        for p in raw
    ][:limit]


async def _fetch_pr_files(client: httpx.AsyncClient, repo: str, pr_number: int) -> list[str]:
    try:
        r = await client.get(
            f"{_BASE}/repos/{repo}/pulls/{pr_number}/files",
            headers=_headers(),
            params={"per_page": 100},
        )
        _raise_for_status(r, repo)
        return [f["filename"] for f in r.json()]
    except Exception:
        return []


_ISSUE_REF = re.compile(r"(?:fixes|closes|resolves)\s+#\d+", re.IGNORECASE)


def _prioritize_open_prs(prs: list[dict], limit: int) -> list[dict]:
    """Issue-referencing PRs first (most likely to overlap with proposals), then by recency."""
    with_refs = [p for p in prs if _ISSUE_REF.search(p.get("body") or "")]
    without_refs = [p for p in prs if p not in with_refs]
    return (with_refs + without_refs)[:limit]


@cached("open_prs")
async def fetch_open_prs(repo: str, limit: int = 15) -> list[dict]:
    max_pages = get_settings().github_max_pages
    async with httpx.AsyncClient() as client:
        raw = await _paginate(
            client,
            f"{_BASE}/repos/{repo}/pulls",
            params={"state": "open", "per_page": 100, "sort": "updated"},
            repo=repo,
            max_pages=max_pages,
        )
    selected = _prioritize_open_prs(raw[:50], limit)
    async with httpx.AsyncClient() as client:
        files_list = await asyncio.gather(*[_fetch_pr_files(client, repo, p["number"]) for p in selected])
    return [
        {
            "number": p["number"],
            "title": p["title"],
            "body": (p["body"] or "")[:400],
            "files": files,
            "url": p["html_url"],
        }
        for p, files in zip(selected, files_list)
    ]


async def fetch_all(repo: str) -> tuple[dict, list[dict], list[dict], list[dict]]:
    return await asyncio.gather(
        fetch_repo_info(repo),
        fetch_issues(repo, limit=60),
        fetch_prs(repo, state="closed", limit=30),
        fetch_open_prs(repo, limit=15),
    )
