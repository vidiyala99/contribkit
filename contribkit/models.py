from typing import Literal
from pydantic import BaseModel


class Proposal(BaseModel, strict=True):
    title: str
    problem: str
    approach: str
    files: list[str]
    effort: Literal["low", "medium", "high"]
    pr_title: str
    pr_body: str
