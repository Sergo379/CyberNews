import os
from datetime import datetime, timezone
from enum import StrEnum
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session


class Role(StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    SUPER_ADMIN = "super_admin"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


bearer = HTTPBearer(auto_error=False, scheme_name="AccessToken")
admin_header = APIKeyHeader(name="X-Admin-Session", auto_error=False, scheme_name="AdminSession")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def secret_setting(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 43 or not value.isascii() or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be an ASCII secret of at least 43 characters without whitespace")
    return value


def require_service_key(request: Request, expected: str) -> None:
    supplied = request.headers.get("X-Internal-Key", "")
    if not compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401)


def token_value(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or len(credentials.credentials) > 2048 or not credentials.credentials.isascii():
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials


def get_db(request: Request):
    with request.app.state.database.sessions(expire_on_commit=False) as db:
        yield db


Db = Annotated[Session, Depends(get_db)]
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
AdminHeader = Annotated[str | None, Depends(admin_header)]
