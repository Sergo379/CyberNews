from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from cybernews_runtime.audit import Reason


class TargetType(StrEnum):
    COMMENT = "comment"
    ARTICLE = "article"
    USER = "user"


class ReportStatus(StrEnum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RestrictionCreate(Input):
    user_id: UUID
    reason: Reason


class RestrictionLift(Input):
    reason: Reason


class RestrictionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_by: UUID
    reason: str
    created_at: datetime
    active: bool
    lifted_at: datetime | None
    lifted_by: UUID | None


class ReportCreate(Input):
    target_type: TargetType
    target_id: UUID
    reason: Reason
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class ReportReview(Input):
    status: Literal[ReportStatus.REVIEWED, ReportStatus.REJECTED]
    reason: Reason | None = None


class ReportView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    author_id: UUID
    target_type: TargetType
    target_id: UUID
    reason: str
    description: str | None
    created_at: datetime
    status: ReportStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None


class CommentPermission(BaseModel):
    user_id: UUID
    allowed: bool
    reason: Literal["allowed", "comment_restricted", "account_suspended"]


class Stats(BaseModel):
    actions: dict[str, int]
