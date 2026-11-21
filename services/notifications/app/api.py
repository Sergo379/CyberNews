from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from cybernews_runtime.audit import Limit, Offset
from cybernews_runtime.news import CATEGORIES
from cybernews_runtime.security import Db, utc_now
from cybernews_runtime.service_client import Articles, CurrentUser

from .models import Notification, Subscription

router = APIRouter(tags=["notifications"])


class SubscriptionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    created_at: datetime


class NotificationView(BaseModel):
    id: UUID
    article_id: UUID | None
    category: str | None
    title: str | None
    available: bool
    event_type: str
    created_at: datetime
    read: bool
    read_at: datetime | None
    event_id: UUID


class NotificationPage(BaseModel):
    service: str = "notifications"
    status: str = "ok"
    items: list[NotificationView]
    total: int
    limit: int
    offset: int


class UnreadCount(BaseModel):
    count: int


class ReadCount(BaseModel):
    updated: int


def category(value: str) -> str:
    if value not in CATEGORIES:
        raise HTTPException(422)
    return value


@router.get("/subscriptions", response_model=list[SubscriptionView])
def subscriptions(actor: CurrentUser, db: Db):
    return list(db.scalars(select(Subscription).where(Subscription.user_id == actor.id).order_by(Subscription.category)))


@router.put("/subscriptions/{category_id}", response_model=SubscriptionView)
def subscribe(category_id: str, actor: CurrentUser, db: Db):
    item = category(category_id)
    db.execute(insert(Subscription).values(user_id=actor.id, category=item).on_conflict_do_nothing())
    row = db.get(Subscription, (actor.id, item))
    db.commit()
    return row


@router.delete("/subscriptions/{category_id}", status_code=204)
def unsubscribe(category_id: str, actor: CurrentUser, db: Db):
    item = category(category_id)
    db.execute(delete(Subscription).where(Subscription.user_id == actor.id, Subscription.category == item))
    db.commit()


@router.get("/", response_model=NotificationPage)
def notifications(actor: CurrentUser, articles: Articles, db: Db,
                  limit: Limit = 20, offset: Offset = 0, unread: bool = False):
    filters = [Notification.user_id == actor.id]
    if unread:
        filters.append(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(Notification).where(*filters))
    rows = list(db.scalars(select(Notification).where(*filters).order_by(
        Notification.created_at.desc(), Notification.id.desc(),
    ).limit(limit).offset(offset)))
    available = articles.available(list(dict.fromkeys(row.article_id for row in rows)))
    items = []
    for row in rows:
        article = available.get(row.article_id)
        items.append(NotificationView(
            id=row.id, article_id=row.article_id if article else None,
            category=row.category if article else None, title=article.title if article else None,
            event_type=row.event_type, available=article is not None, created_at=row.created_at,
            read=row.read_at is not None, read_at=row.read_at, event_id=row.event_id,
        ))
    return NotificationPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(actor: CurrentUser, db: Db):
    return UnreadCount(count=db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == actor.id, Notification.read_at.is_(None),
    )))


@router.patch("/{notification_id}/read", status_code=204)
def mark_read(notification_id: UUID, actor: CurrentUser, db: Db):
    row = db.scalar(update(Notification).where(
        Notification.id == notification_id, Notification.user_id == actor.id,
    ).values(read_at=func.coalesce(Notification.read_at, utc_now())).returning(Notification.id))
    if row is None:
        raise HTTPException(404)
    db.commit()


@router.post("/read-all", response_model=ReadCount)
def read_all(actor: CurrentUser, db: Db):
    result = db.execute(update(Notification).where(
        Notification.user_id == actor.id, Notification.read_at.is_(None),
    ).values(read_at=utc_now()))
    db.commit()
    return ReadCount(updated=result.rowcount)
