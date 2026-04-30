import json
import anthropic
from pydantic import ValidationError
from contribkit.config import get_settings
from contribkit.exceptions import LLMParseError
from contribkit.models import Proposal
from contribkit.synthesis.parsing import extract_tagged_json


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)

_PROMPT = """\
You are a senior open source engineer and technical researcher acting as a research partner.

Analyze this repository and generate {num_proposals} actionable contribution proposals. Each proposal should either:
- Fix a real gap or pain point surfaced by multiple issues
- Add a feature that has strong community demand (comments/reactions)
- Improve developer experience based on recurring PR patterns
- Address architectural gaps visible in the source code

## Repo: {repo}
{repo_info}

## Open Issues (by update recency)
{issues}

## Recent Merged PRs (what the team has been shipping)
{merged_prs}

## Open PRs (avoid duplicating work already in progress)
{open_prs}
{source_section}
{focus_directive}
{prior_proposals}
For each proposal output a JSON object with:
- title: short PR title
- problem: what's broken or missing (cite issue numbers or file/function names where relevant)
- approach: concrete implementation plan (2-4 sentences)
- files: list of files/modules likely involved
- effort: "low" | "medium" | "high"
- pr_title: ready-to-use PR title
- pr_body: ready-to-use PR description (markdown, include motivation + changes)

Wrap the JSON array in <proposals>...</proposals> tags. No other text outside the tags.
"""


def _fmt_issues(issues: list[dict]) -> str:
    lines = []
    for i in issues[:25]:
        label_str = ", ".join(i["labels"]) or "none"
        lines.append(
            f"#{i['number']} [{label_str}] +{i['reactions']}👍 {i['comments']}💬  {i['title']}\n"
            f"  {i['body'][:300].strip()}"
        )
    return "\n\n".join(lines)


def _fmt_prs(prs: list[dict]) -> str:
    return "\n".join(f"#{p['number']}: {p['title']}" for p in prs[:20])


def _fmt_open_prs(prs: list[dict]) -> str:
    lines = []
    for p in prs:
        line = f"#{p['number']}: {p['title']}"
        body = (p.get("body") or "").strip()
        if body:
            line += f"\n  {body[:300]}"
        files = p.get("files") or []
        if files:
            line += f"\n  Files: {', '.join(files[:15])}"
        lines.append(line)
    return "\n\n".join(lines)


def generate_proposals(
    repo: str,
    repo_info: dict,
    issues: list[dict],
    merged_prs: list[dict],
    open_prs: list[dict],
    source_code: str | None = None,
    codebase_graph: str | None = None,
    prior_proposals: str = "",
    num_proposals: int = 5,
    focus: list[str] | None = None,
) -> list[dict]:
    source_section = ""
    if codebase_graph:
        source_section = f"\n{codebase_graph}\n"
    elif source_code:
        source_section = f"\n## Source Code\n{source_code}\n"

    focus_directive = ""
    if focus:
        patterns_str = ", ".join(f"`{p}`" for p in focus)
        focus_directive = f"\n## Focus Constraint\nGenerate proposals exclusively for these modules/paths: {patterns_str}. Ignore areas outside this scope.\n"

    prompt = _PROMPT.format(
        repo=repo,
        repo_info=json.dumps(repo_info, indent=2),
        issues=_fmt_issues(issues),
        merged_prs=_fmt_prs(merged_prs),
        open_prs=_fmt_open_prs(open_prs),
        source_section=source_section,
        focus_directive=focus_directive,
        prior_proposals=f"{prior_proposals}\n" if prior_proposals else "",
        num_proposals=num_proposals,
    )

    messages = [{"role": "user", "content": prompt}]
    max_tokens = min(4096 + num_proposals * 1200, 16000)
    last_error: LLMParseError | None = None

    for attempt in range(3):
        response = _client().messages.create(
            model=get_settings().anthropic_model,
            max_tokens=max_tokens,
            messages=messages,
        )
        raw = response.content[0].text

        try:
            raw_list = extract_tagged_json(raw, "proposals")
        except LLMParseError as e:
            last_error = e
            # Retry: show Claude what it returned and ask it to fix the format
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    "Your response could not be parsed as JSON inside <proposals>...</proposals> tags. "
                    "Please rewrite your answer, this time wrapping a valid JSON array in "
                    "<proposals>...</proposals> with no other text outside the tags."
                )},
            ]
            continue

        if not isinstance(raw_list, list):
            last_error = LLMParseError(f"Expected a JSON array, got {type(raw_list).__name__}")
            continue

        validated = []
        errors = []
        for i, item in enumerate(raw_list):
            try:
                validated.append(Proposal.model_validate(item).model_dump())
            except ValidationError as e:
                errors.append(f"proposal[{i}]: {e.errors()[0]['loc']} {e.errors()[0]['msg']}")

        if errors:
            last_error = LLMParseError("Proposal schema validation failed:\n" + "\n".join(errors))
            continue

        return validated

    raise last_error
