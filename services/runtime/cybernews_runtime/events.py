from typing import Literal
from uuid import UUID

from pydantic import field_validator

from .news import CATEGORIES, Input, Instant


class ArticlePublished(Input):
    event_id: UUID
    event_type: Literal["article.published"]
    event_version: Literal[1]
    article_id: UUID
    category: str
    source_id: UUID | None
    published_at: Instant | None
    created_at: Instant

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError("Unknown article category")
        return value
