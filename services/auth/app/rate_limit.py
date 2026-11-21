from datetime import timedelta
from hmac import digest

from fastapi import HTTPException, Request
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from cybernews_runtime.security import utc_now

from .config import jwt_secret
from .models import RateBucket

WINDOW_SECONDS = 60


def limit_attempt(request: Request, operation: str, identity: str) -> None:
    now = utc_now()
    expires = now + timedelta(seconds=WINDOW_SECONDS)
    peer = request.client.host if request.client else "unknown"
    buckets = ((f"{operation}:peer:{peer}", 120), (f"{operation}:account:{identity}", 5))
    blocked = False
    with request.app.state.database.sessions.begin() as db:
        for bucket, limit in buckets:
            key = digest(jwt_secret.encode(), bucket.encode(), "sha256").hex()
            expired = RateBucket.expires_at <= now
            query = insert(RateBucket).values(key=key, count=1, expires_at=expires)
            query = query.on_conflict_do_update(
                index_elements=[RateBucket.key],
                set_={
                    "count": case((expired, 1), else_=RateBucket.count + 1),
                    "expires_at": case((expired, expires), else_=RateBucket.expires_at),
                },
                where=expired | (RateBucket.count < limit),
            ).returning(RateBucket.key)
            if db.scalar(query) is None:
                blocked = True
                break
        db.execute(delete(RateBucket).where(RateBucket.expires_at < now - timedelta(minutes=10)))
    if blocked:
        raise HTTPException(429, headers={"Retry-After": str(WINDOW_SECONDS)})
