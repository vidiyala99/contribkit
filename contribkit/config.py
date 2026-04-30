from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    anthropic_api_key: str = ""
    cache_dir: str = str(Path.home() / ".contribkit")
    cache_ttl: int = 1800  # seconds
    anthropic_model: str = "claude-sonnet-4-6"
    max_source_bytes: int = 200_000
    github_max_pages: int = 5

    model_config = {"env_file": ".env"}

    @model_validator(mode="after")
    def _require_keys(self) -> "Settings":
        missing = [name for name, val in [
            ("GITHUB_TOKEN", self.github_token),
            ("ANTHROPIC_API_KEY", self.anthropic_api_key),
        ] if not val]
        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                "Set them in your .env file or environment."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    from pydantic import ValidationError
    from contribkit.exceptions import ConfigurationError
    try:
        return Settings()
    except ValidationError as e:
        msgs = "; ".join(err["msg"] for err in e.errors())
        raise ConfigurationError(msgs) from e
