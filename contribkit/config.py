from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    github_token: str = ""
    anthropic_api_key: str = ""

    model_config = {"env_file": ".env"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
