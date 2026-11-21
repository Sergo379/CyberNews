from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from cybernews_runtime.security import utc_now

from .models import MutationBucket

LIMITS = {"comments": 12, "edits": 30, "reactions": 120, "bookmarks": 60}


def count_attempt(request: Request, user_id, operation: str) -> None:
    now = utc_now()
    expires = now + timedelta(seconds=60)
    expired = MutationBucket.expires_at <= now
    statement = insert(MutationBucket).values(user_id=user_id, operation=operation, count=1, expires_at=expires)
    with request.app.state.database.sessions.begin() as db:
        allowed = db.scalar(statement.on_conflict_do_update(
            index_elements=[MutationBucket.user_id, MutationBucket.operation],
            set_={
                "count": case((expired, 1), else_=MutationBucket.count + 1),
                "expires_at": case((expired, expires), else_=MutationBucket.expires_at),
            },
            where=expired | (MutationBucket.count < LIMITS[operation]),
        ).returning(MutationBucket.count))
        if allowed == 1:
            db.execute(delete(MutationBucket).where(MutationBucket.expires_at < now - timedelta(minutes=10)))
    if allowed is None:
        raise HTTPException(429, headers={"Retry-After": "60"})
