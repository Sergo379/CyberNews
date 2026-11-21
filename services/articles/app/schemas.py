from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from cybernews_runtime.news import ArticleStatus, Content, ContentMode, Input, Instant, Label, Language, Summary, Title, WebUrl

CategoryId = Literal["vulnerabilities", "malware", "data-breaches", "cyberattacks", "research", "software-security", "other"]
EditableStatus = Literal[ArticleStatus.DRAFT, ArticleStatus.PUBLISHED]
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class OriginalCreate(Input):
    title: Title
    summary: Summary | None = None
    content: Content
    author: Label | None = None
    category: CategoryId = "other"
    language: Language = "en"
    published_at: Instant | None = None
    image_url: WebUrl | None = None
    status: EditableStatus = ArticleStatus.DRAFT


class EditorialUpdate(Input):
    title: Title | None = None
    summary: Summary | None = None
    content: Content | None = None
    author: Label | None = None
    category: CategoryId | None = None
    language: Language | None = None
    published_at: Instant | None = None
    image_url: WebUrl | None = None
    status: EditableStatus | None = None

    @model_validator(mode="after")
    def valid_changes(self):
        required = {"title", "content", "category", "language", "status"}
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set & required
        ):
            raise ValueError("Supply editable fields with valid values")
        return self


class ArticleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    summary: str | None
    content_mode: ContentMode
    source_id: UUID | None
    source_name: str
    source_url: str | None
    original_url: str | None
    author: str | None
    category: CategoryId
    language: str
    published_at: datetime | None
    collected_at: datetime
    image_url: str | None


class ArticleView(ArticleListItem):
    content: str | None
    external_guid: str | None
    updated_at: datetime
    status: ArticleStatus


class ArticlePage(BaseModel):
    service: Literal["articles"] = "articles"
    status: Literal["ok"] = "ok"
    items: list[ArticleListItem]
    total: int
    limit: int
    offset: int


class CategoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: CategoryId
    name: str


class SourceView(BaseModel):
    id: UUID | None
    name: str
    url: str | None
    count: int
