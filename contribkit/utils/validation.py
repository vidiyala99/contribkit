import re

_SLUG_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")


def parse_repo_slug(raw: str) -> tuple[str, str]:
    """Validate and parse 'owner/repo' slug. Raises ValueError on bad input."""
    raw = raw.strip()
    if not _SLUG_RE.match(raw) or len(raw) > 200:
        raise ValueError(
            f"Invalid repo slug {raw!r}. Expected format: owner/repo "
            "(alphanumeric, hyphens, underscores, dots only)."
        )
    owner, name = raw.split("/", 1)
    return owner, name


def slug_to_filename(repo: str) -> str:
    """Convert 'owner/repo' to a safe filename component."""
    return repo.replace("/", "__")
