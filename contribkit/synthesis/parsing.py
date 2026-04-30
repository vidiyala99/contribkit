"""Shared LLM response parsing with multi-stage fallback."""

import json
import re

from contribkit.exceptions import LLMParseError

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_tagged_json(text: str, tag: str) -> list | dict:
    """
    Extract JSON from an LLM response using three fallback strategies:
      1. XML-style tag: <tag>...</tag>
      2. Markdown code fence: ```json ... ```
      3. Bare json.loads on the full text

    Raises LLMParseError if all three fail.
    """
    # Strategy 1: tag match
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass  # fall through to next strategy

    # Strategy 2: markdown code fence
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Strategy 3: bare text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    raise LLMParseError(
        f"Could not parse JSON from model response (tried tag <{tag}>, "
        f"markdown fence, and bare parse).\nResponse snippet: {text[:400]}"
    )
