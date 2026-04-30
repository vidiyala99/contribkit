import asyncio
import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from contribkit.config import get_settings
from contribkit.exceptions import ContribKitError
from contribkit.utils.validation import parse_repo_slug
from contribkit.ingestion import cache as _cache
from contribkit.ingestion.cache import clear as cache_clear
from contribkit.ingestion.github import fetch_all
from contribkit.ingestion.source import read_source_files
from contribkit.ingestion.graph import build_graph, load_graph, graph_exists, graph_to_context, graph_to_focused_context
from contribkit.synthesis.proposals import generate_proposals
from contribkit.proposals.store import save_proposals, list_proposals, set_status, open_proposals_context

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
    num_proposals: int = typer.Option(5, "--num-proposals", "-p", help="Number of proposals to generate", min=1, max=20),
    focus: list[str] = typer.Option([], "--focus", "-f", help="Glob pattern(s) to scope proposals to specific modules (e.g. 'contribkit/ingestion/*.py')"),
):
    """Fetch repo signals and generate ranked contribution proposals."""
    try:
        parse_repo_slug(repo)
    except ValueError as e:
        console.print(Panel(f"[red]{e}[/red]", title="[bold red]Invalid repo slug[/bold red]", border_style="red"))
        raise SystemExit(1)

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
        codebase_graph = None
        if source:
            if graph_exists(repo):
                g = load_graph(repo)
                codebase_graph = graph_to_focused_context(g, focus) if focus else graph_to_context(g)
                import time as _time
                age_h = (_time.time() - g.get("analyzed_at", 0)) / 3600
                focus_hint = f" · focus: {', '.join(focus)}" if focus else ""
                console.print(f"[dim]Using codebase graph for {repo} (built {age_h:.0f}h ago{focus_hint})[/dim]\n")
            else:
                source_code, excluded = read_source_files(source, get_settings().max_source_bytes)
                console.print(f"[dim]No graph found — reading raw source from {source}. Run `contribkit index` to build a graph.[/dim]\n")
                if excluded:
                    console.print(f"[yellow]Source size cap reached — {len(excluded)} file(s) excluded from analysis:[/yellow]")
                    for ex in excluded[:5]:
                        console.print(f"  [dim]{ex}[/dim]")
                    if len(excluded) > 5:
                        console.print(f"  [dim]... and {len(excluded) - 5} more[/dim]")
                    console.print()

        prior = open_proposals_context(repo)
        if prior:
            console.print(f"[dim]Loaded prior open proposals — Claude will not re-propose these.[/dim]\n")

        if focus:
            console.print(f"[dim]Focus: {', '.join(focus)}[/dim]\n")

        with console.status("[bold blue]Generating proposals with Claude..."):
            proposals = generate_proposals(repo, repo_info, open_issues, merged_prs, open_prs, source_code, codebase_graph, prior, num_proposals, focus or None)

        graph_ts = load_graph(repo).get("analyzed_at") if graph_exists(repo) else None
        new_props, existing_props = save_proposals(repo, proposals, graph_ts)

        if existing_props:
            console.print(f"[bold green]{len(new_props)} new · [dim]{len(existing_props)} already tracked[/dim][/bold green]\n")
        else:
            console.print(f"[bold green]{len(proposals)} proposals generated[/bold green]\n")

        new_titles = {p["title"] for p in new_props}
        for idx, p in enumerate(proposals, 1):
            effort = p.get("effort", "medium")
            color = EFFORT_COLOR.get(effort, "white")
            is_new = p["title"] in new_titles

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

            tag = " [bold green]NEW[/bold green]" if is_new else " [dim]tracked[/dim]"
            console.print(Panel(body, title=f"[bold]#{idx}  {p['title']}[/bold]{tag}", border_style="blue" if is_new else "dim", expand=False))
            console.print()

    try:
        asyncio.run(run())
    except ContribKitError as e:
        console.print(Panel(f"[red]{e}[/red]", title="[bold red]Error[/bold red]", border_style="red"))
        raise SystemExit(1)


@app.command()
def index(
    repo: str = typer.Argument(..., help="GitHub repo slug, e.g. dagster-io/dagster"),
    source: str = typer.Argument(..., help="Path to local source directory to analyze"),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if graph already exists"),
):
    """Build a persistent codebase graph from local source (run once, reused by analyze)."""
    try:
        parse_repo_slug(repo)
    except ValueError as e:
        console.print(Panel(f"[red]{e}[/red]", title="[bold red]Invalid repo slug[/bold red]", border_style="red"))
        raise SystemExit(1)

    if graph_exists(repo) and not force:
        g = load_graph(repo)
        import time as _time
        age_h = (_time.time() - g.get("analyzed_at", 0)) / 3600
        console.print(f"[yellow]Graph for {repo} already exists (built {age_h:.0f}h ago). Use --force to rebuild.[/yellow]")
        return

    try:
        with console.status(f"[bold blue]Analyzing codebase at {source}..."):
            graph = build_graph(repo, source)

        console.print(f"\n[bold green]Graph built for {repo}[/bold green]")
        console.print(f"  Modules:      [cyan]{len(graph.get('modules', []))}[/cyan]")
        console.print(f"  Abstractions: [cyan]{len(graph.get('abstractions', []))}[/cyan]")
        console.print(f"  Pain points:  [cyan]{len(graph.get('pain_points', []))}[/cyan]")
        console.print(f"\n[dim]Architecture: {graph.get('architecture_summary', '')[:200]}[/dim]")
        console.print(f"\n[dim]Run `contribkit analyze {repo}` to use this graph.[/dim]")

    except ContribKitError as e:
        console.print(Panel(f"[red]{e}[/red]", title="[bold red]Error[/bold red]", border_style="red"))
        raise SystemExit(1)


STATUS_COLOR = {"open": "cyan", "in_progress": "yellow", "done": "green", "dismissed": "dim"}


@app.command(name="proposals")
def proposals_cmd(
    repo: str = typer.Argument(..., help="GitHub repo slug"),
    status: str = typer.Option(None, "--status", "-s", help="Filter by status: open, in_progress, done, dismissed"),
    done: str = typer.Option(None, "--done", help="Mark a proposal ID as done"),
    dismiss: str = typer.Option(None, "--dismiss", help="Mark a proposal ID as dismissed"),
    wip: str = typer.Option(None, "--wip", help="Mark a proposal ID as in_progress"),
):
    """List and manage tracked proposals for a repo."""
    if done:
        ok = set_status(repo, done, "done")
        console.print(f"[green]Marked {done} as done.[/green]" if ok else f"[red]ID {done} not found.[/red]")
        return
    if dismiss:
        ok = set_status(repo, dismiss, "dismissed")
        console.print(f"[dim]Dismissed {dismiss}.[/dim]" if ok else f"[red]ID {dismiss} not found.[/red]")
        return
    if wip:
        ok = set_status(repo, wip, "in_progress")
        console.print(f"[yellow]Marked {wip} as in_progress.[/yellow]" if ok else f"[red]ID {wip} not found.[/red]")
        return

    items = list_proposals(repo, status=status)  # type: ignore[arg-type]
    if not items:
        console.print(f"[dim]No proposals found for {repo}" + (f" with status={status}" if status else "") + "[/dim]")
        return

    console.print(f"\n[bold]{repo}[/bold] — {len(items)} proposal(s)\n")
    for p in items:
        s = p["status"]
        color = STATUS_COLOR.get(s, "white")
        console.print(f"  [{color}]{s:12}[/{color}]  [dim]{p['_id']}[/dim]  {p['title']}")
    console.print()
    console.print("[dim]Mark done:    contribkit proposals <repo> --done <id>[/dim]")
    console.print("[dim]Mark wip:     contribkit proposals <repo> --wip <id>[/dim]")
    console.print("[dim]Dismiss:      contribkit proposals <repo> --dismiss <id>[/dim]")


@app.command()
def cache(
    repo: str = typer.Option(None, "--repo", "-r", help="Clear cache only for this repo slug"),
):
    """Clear cached GitHub API responses (all repos, or a specific one)."""
    deleted = cache_clear(repo)
    if deleted:
        for path in deleted:
            console.print(f"[dim]deleted {path}[/dim]")
        console.print(f"[green]Cleared {len(deleted)} cache file(s).[/green]")
    else:
        console.print("[yellow]Nothing to clear.[/yellow]")


if __name__ == "__main__":
    app()
