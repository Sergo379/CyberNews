from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .audit import Reason
from .news import Input
from .security import Role

CommentStatus = Literal["published", "hidden", "deleted"]
ModerationAction = Literal["hide", "restore"]


class CommentTarget(BaseModel):
    id: UUID
    article_id: UUID
    author_id: UUID
    status: CommentStatus


class ReviewComment(CommentTarget):
    model_config = ConfigDict(from_attributes=True)

    nickname: str
    body: str
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None
    removed_at: datetime | None
    moderated_by: UUID | None
    moderation_reason: str | None


class ModerationInstruction(Input):
    command_id: UUID
    action: ModerationAction
    actor_id: UUID
    actor_role: Literal[Role.MODERATOR, Role.SUPER_ADMIN]
    reason: Reason


class ModerationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comment_id: UUID
    actor_id: UUID
    actor_role: Role
    action: ModerationAction
    reason: str
    result: Literal["applied", "no_change"]
    status: CommentStatus
    request_id: str
    created_at: datetime
