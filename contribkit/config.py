from __future__ import annotations
from functools import lru_cache
from pathlib import Path
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
