from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from cybernews_runtime.security import AccountStatus, AdminHeader, Bearer, Db, Role, token_value, utc_now

from .accounts import get_user, govern, session_hash
from .models import AdminSession, User
from .tokens import Claims, decode_token


@dataclass(frozen=True)
class Principal:
    user: User
    claims: Claims


def get_principal(db: Session, credentials, *, lock: bool = False) -> Principal:
    claims = decode_token(token_value(credentials))
    user = get_user(db, claims.user_id, lock=lock)
    if user is None or user.status != AccountStatus.ACTIVE or user.auth_version != claims.version:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    return Principal(user, claims)


def active_principal(db: Db, credentials: Bearer) -> Principal:
    return get_principal(db, credentials)


def locked_principal(db: Db, credentials: Bearer) -> Principal:
    return get_principal(db, credentials, lock=True)


def require_admin_role(user: User) -> None:
    if user.role == Role.USER:
        raise HTTPException(403)


def require_admin_session(db: Session, principal: Principal, token: str | None) -> AdminSession:
    require_admin_role(principal.user)
    if token is None or len(token) != 43:
        raise HTTPException(403)
    session = db.get(AdminSession, session_hash(token))
    if (session is None or session.user_id != principal.user.id or
            session.access_jti != principal.claims.jti or session.expires_at <= utc_now()):
        raise HTTPException(403)
    return session


def administrator(db: Db, credentials: Bearer, admin_session: AdminHeader) -> Principal:
    principal = get_principal(db, credentials)
    require_admin_session(db, principal, admin_session)
    return principal


def super_admin_write(db: Db, credentials: Bearer, admin_session: AdminHeader) -> Principal:
    # Serialize cross-account writes before locking the actor and target.
    govern(db)
    principal = get_principal(db, credentials, lock=True)
    require_admin_session(db, principal, admin_session)
    if principal.user.role != Role.SUPER_ADMIN:
        raise HTTPException(403)
    return principal


Active = Annotated[Principal, Depends(active_principal)]
Locked = Annotated[Principal, Depends(locked_principal)]
Administrator = Annotated[Principal, Depends(administrator)]
SuperAdminWrite = Annotated[Principal, Depends(super_admin_write)]
