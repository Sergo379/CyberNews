from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Query
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import DateTime, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .logs import request_id

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


class AuditFields:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(48))
    target_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[str] = mapped_column(String(128))


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID
    action: str
    target_id: UUID
    created_at: datetime
    reason: str | None
    result: str
    request_id: str


def add_event(db, model, actor_id, action, target_id, reason=None, result="applied"):
    event = model(
        actor_id=actor_id, action=action, target_id=target_id, reason=reason,
        result=result, request_id=request_id.get() or uuid4().hex,
    )
    db.add(event)
    return event


def audit_query(model, actor_id, limit, offset):
    query = select(model).order_by(model.created_at.desc(), model.id.desc()).limit(limit).offset(offset)
    if actor_id is not None:
        query = query.where(model.actor_id == actor_id)
    return query
