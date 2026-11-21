from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException

from cybernews_runtime.security import utc_now

from .config import access_ttl, jwt_secret
from .models import User

ISSUER = "cybernews-auth"
AUDIENCE = "cybernews-api"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class Claims:
    user_id: UUID
    jti: UUID
    version: int
    expires_at: datetime


def issue_token(user: User) -> str:
    now = utc_now()
    return jwt.encode(
        {
            "sub": str(user.id), "iat": now, "exp": now + timedelta(seconds=access_ttl),
            "iss": ISSUER, "aud": AUDIENCE, "jti": str(uuid4()), "type": "access",
            "ver": user.auth_version,
        },
        jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> Claims:
    try:
        payload = jwt.decode(
            token, jwt_secret, algorithms=[ALGORITHM], issuer=ISSUER, audience=AUDIENCE,
            options={"require": ["sub", "iat", "exp", "iss", "aud", "jti", "type", "ver"],
                     "strict_aud": True},
        )
        if payload["type"] != "access" or type(payload["ver"]) is not int:
            raise ValueError("Invalid token claims")
        return Claims(
            UUID(payload["sub"]), UUID(payload["jti"]), payload["ver"],
            datetime.fromtimestamp(payload["exp"], timezone.utc),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError, OSError):
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"}) from None
