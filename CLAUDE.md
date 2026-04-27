# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**contribkit** is a CLI tool that acts as an OSS research partner. Given a GitHub repo slug, it fetches signals (open issues, merged PRs, open PRs) and uses Claude to generate ranked, actionable contribution proposals with draft PR titles and bodies.

## Setup

```bash
pip install -e .
cp .env.example .env  # fill in GITHUB_TOKEN and ANTHROPIC_API_KEY
```

## Running

```bash
contribkit analyze dagster-io/dagster
contribkit analyze dagster-io/dagster --issues 100
```

Or directly:

```bash
python -m contribkit.cli analyze dagster-io/dagster
```

## Architecture

The codebase has two layers connected by the CLI:

**`contribkit/ingestion/github.py`** — async GitHub REST API client using `httpx`. `fetch_all()` fires four concurrent requests (repo info, open issues, merged PRs, open PRs) via `asyncio.gather`. Issue bodies are truncated to 1200 chars and PR bodies to 600 chars to control token usage.

**`contribkit/synthesis/proposals.py`** — synchronous Claude API call (claude-sonnet-4-6). Formats the fetched data into a single prompt and parses the response by extracting a `<proposals>...</proposals>` XML tag containing a JSON array. The top 25 issues and 20 PRs are included in the prompt.

**`contribkit/cli.py`** — Typer CLI. The single `analyze` command wraps the async pipeline in `asyncio.run()` and renders proposals as Rich panels with effort-level color coding.

**`contribkit/config.py`** — Pydantic `BaseSettings` with `lru_cache`. Reads `GITHUB_TOKEN` and `ANTHROPIC_API_KEY` from `.env`.

## Key Design Constraints

- The synthesis step is synchronous (Claude SDK); only the ingestion step is async.
- Proposal parsing relies on `<proposals>...</proposals>` tag extraction — changes to the prompt must preserve this contract.
- The model is hardcoded to `claude-sonnet-4-6` in `proposals.py:73`.
