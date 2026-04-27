import asyncio
import httpx
from contribkit.config import get_settings

_BASE = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_settings().github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def fetch_repo_info(repo: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_BASE}/repos/{repo}", headers=_headers())
        r.raise_for_status()
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


async def fetch_issues(repo: str, limit: int = 50) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_BASE}/repos/{repo}/issues",
            headers=_headers(),
            params={"state": "open", "per_page": min(limit, 100), "sort": "updated"},
        )
        r.raise_for_status()
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
            for i in r.json()
            if "pull_request" not in i  # issues endpoint includes PRs
        ]


async def fetch_prs(repo: str, state: str = "closed", limit: int = 30) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_BASE}/repos/{repo}/pulls",
            headers=_headers(),
            params={"state": state, "per_page": min(limit, 100), "sort": "updated"},
        )
        r.raise_for_status()
        return [
            {
                "number": p["number"],
                "title": p["title"],
                "body": (p["body"] or "")[:600],
                "state": p["state"],
                "merged_at": p.get("merged_at"),
                "url": p["html_url"],
            }
            for p in r.json()
        ]


async def fetch_all(repo: str) -> tuple[dict, list[dict], list[dict], list[dict]]:
    return await asyncio.gather(
        fetch_repo_info(repo),
        fetch_issues(repo, limit=60),
        fetch_prs(repo, state="closed", limit=30),
        fetch_prs(repo, state="open", limit=30),
    )
