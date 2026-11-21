import re
from datetime import datetime
from html import unescape
from typing import Literal
from uuid import UUID

import nh3
from pydantic import BaseModel, Field, field_validator

from cybernews_runtime.contracts import ArticleReference
from cybernews_runtime.news import Input

Reaction = Literal["like", "dislike"]
HTML_TAG = re.compile(r"<\s*(?:/?[a-zA-Z]|[!?])")


class CommentInput(Input):
    body: str = Field(max_length=20_000)

    @field_validator("body")
    @classmethod
    def plain_body(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 5000 or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
            raise ValueError("Comment must contain 1–5000 text characters")
        if HTML_TAG.search(value) or "&" in value:
            value = unescape(nh3.clean(
                value, tags=set(), clean_content_tags={"script", "style", "iframe", "svg", "object", "template"},
            )).strip()
            if HTML_TAG.search(value):
                raise ValueError("Invalid embedded markup")
        if not 1 <= len(value) <= 5000 or "\x00" in value:
            raise ValueError("Comment must contain 1–5000 text characters")
        return value


class ReactionInput(Input):
    reaction: Reaction


class ReactionView(BaseModel):
    likes: int = 0
    dislikes: int = 0
    my_reaction: Reaction | None = None


class CommentView(ReactionView):
    id: UUID
    article_id: UUID
    author_id: UUID
    nickname: str
    body: str
    created_at: datetime
    updated_at: datetime
    edited: bool
    edited_at: datetime | None


class CommentPage(BaseModel):
    items: list[CommentView]
    total: int
    limit: int
    offset: int


class BookmarkView(BaseModel):
    article_id: UUID
    bookmarked: bool
    created_at: datetime | None = None


class SavedArticle(BaseModel):
    article_id: UUID
    created_at: datetime
    available: bool
    article: ArticleReference | None = None


class ArticleIds(Input):
    ids: list[UUID] = Field(min_length=1, max_length=100)


class ArticleStats(ReactionView):
    article_id: UUID
    comments: int
    bookmarked: bool | None
