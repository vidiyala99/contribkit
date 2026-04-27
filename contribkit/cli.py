import asyncio
import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from contribkit.exceptions import ContribKitError
from contribkit.ingestion import cache as _cache
from contribkit.ingestion.github import fetch_all
from contribkit.ingestion.source import read_source_files
from contribkit.synthesis.proposals import generate_proposals

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(name="contribkit", help="OSS research partner - surfaces contribution proposals from repo signals.")
console = Console(legacy_windows=False)

EFFORT_COLOR = {"low": "green", "medium": "yellow", "high": "red"}


@app.command()
def analyze(
    repo: str = typer.Argument(..., help="GitHub repo slug, e.g. dagster-io/dagster"),
    issues: int = typer.Option(60, "--issues", "-n", help="Max issues to fetch"),
    source: str = typer.Option(None, "--source", "-s", help="Path to local source directory to include in analysis"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass disk cache and fetch fresh data"),
):
    """Fetch repo signals and generate ranked contribution proposals."""

    _cache.set_bypass(no_cache)

    async def run():
        with console.status(f"[bold blue]Fetching signals from {repo}..."):
            repo_info, open_issues, merged_prs, open_prs = await fetch_all(repo)

        cache_hint = " [dim](cached)[/dim]" if not no_cache else ""
        console.print(
            f"\n[bold]{repo_info['name']}[/bold]  "
            f"stars:{repo_info['stars']:,}  forks:{repo_info['forks']:,}  "
            f"open issues:{repo_info['open_issues_count']}{cache_hint}"
        )
        console.print(f"[dim]{repo_info['description']}[/dim]\n")
        console.print(
            f"Fetched [cyan]{len(open_issues)}[/cyan] issues · "
            f"[cyan]{len(merged_prs)}[/cyan] merged PRs · "
            f"[cyan]{len(open_prs)}[/cyan] open PRs\n"
        )

        source_code = None
        if source:
            source_code = read_source_files(source)
            console.print(f"[dim]Read source from {source}[/dim]\n")

        with console.status("[bold blue]Generating proposals with Claude..."):
            proposals = generate_proposals(repo, repo_info, open_issues, merged_prs, open_prs, source_code)

        console.print(f"[bold green]{len(proposals)} proposals generated[/bold green]\n")

        for idx, p in enumerate(proposals, 1):
            effort = p.get("effort", "medium")
            color = EFFORT_COLOR.get(effort, "white")

            body = Text()
            body.append("Problem\n", style="bold yellow")
            body.append(p["problem"] + "\n\n")
            body.append("Approach\n", style="bold cyan")
            body.append(p["approach"] + "\n\n")
            body.append("Files\n", style="bold")
            body.append(", ".join(p.get("files", [])) + "\n\n")
            body.append("Effort  ", style="bold")
            body.append(effort, style=f"bold {color}")
            body.append("\n\n")
            body.append("── Draft PR ──────────────────────────────\n", style="dim")
            body.append(f"{p['pr_title']}\n\n", style="bold")
            body.append(p["pr_body"])

            console.print(Panel(body, title=f"[bold]#{idx}  {p['title']}[/bold]", border_style="blue", expand=False))
            console.print()

    try:
        asyncio.run(run())
    except ContribKitError as e:
        console.print(Panel(f"[red]{e}[/red]", title="[bold red]Error[/bold red]", border_style="red"))
        raise SystemExit(1)


if __name__ == "__main__":
    app()
