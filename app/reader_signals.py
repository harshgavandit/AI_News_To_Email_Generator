"""Explicit reader choices shared by recommendations and catch-up digests."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.coverage import TOPICS
from app.discovery import search_text


class ReaderFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    liked_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]] = Field(default_factory=list, max_length=12)
    muted_topics: list[str] = Field(default_factory=list, max_length=12)
    companies: list[Annotated[str, Field(min_length=2, max_length=60, pattern=r"^[\p{L}\p{N} &.,+_'-]+$")]] = Field(default_factory=list, max_length=12)

    @field_validator("muted_topics")
    @classmethod
    def valid_topics(cls, values):
        if any(value not in TOPICS for value in values):
            raise ValueError("Choose a supported news topic.")
        return list(dict.fromkeys(values))


def company_matches(article, companies):
    text = " " + search_text(" ".join((article["title"], article.get("cleanSummary") or article.get("description", "")))) + " "
    return [name for name in companies if (phrase := search_text(name)) and f" {phrase} " in text]
