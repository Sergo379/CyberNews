from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from cybernews_runtime.news import ContentMode, Input, Label, Language, RightsReference, SourcePolicy, WebUrl


class SourceCreate(SourcePolicy):
    name: Label
    feed_url: WebUrl
    website_url: WebUrl
    language: Language = "en"
    active: bool = True


class SourcePatch(Input):
    name: Label | None = None
    feed_url: WebUrl | None = None
    website_url: WebUrl | None = None
    language: Language | None = None
    active: bool | None = None
    content_policy: ContentMode | None = None
    rights_reference: RightsReference | None = None
    allow_images: bool | None = None

    @model_validator(mode="after")
    def validate_fields(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set - {"rights_reference"}
        ):
            raise ValueError("Supply valid source settings")
        return self


class SourceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    feed_url: str
    website_url: str
    language: str
    active: bool
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    status: str
    last_error: str | None
    processed_count: int
    content_policy: ContentMode
    rights_reference: str | None
    allow_images: bool
    created_at: datetime
    updated_at: datetime


class SourceRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: UUID
    status: str
    error: str | None
    seen: int
    skipped: int
    created: int
    updated: int
    unchanged: int
    conflicted: int
    started_at: datetime
    finished_at: datetime | None


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trigger: str
    status: str
    source_id: UUID | None
    requested_by: UUID | None
    request_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunView):
    sources: list[SourceRunView]


class StatusView(BaseModel):
    auto_sync: bool
    interval_seconds: int
    active_sources: int
    last_run: RunView | None
