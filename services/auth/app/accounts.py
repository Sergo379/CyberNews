import unicodedata
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cybernews_runtime.security import Role, utc_now

from .models import AdminSession, User
from .passwords import hasher, verify_password
from .schemas import Registration


def nickname_key(nickname: str) -> str:
    return unicodedata.normalize("NFKC", nickname).casefold()


def add_user(db: Session, data: Registration, role: Role = Role.USER, admin_hash: str | None = None) -> User:
    user = User(
        email=data.email.casefold(),
        nickname=data.nickname,
        nickname_key=nickname_key(data.nickname),
        password_hash=hasher.hash(data.password.get_secret_value()),
        role=role,
        admin_password_hash=admin_hash,
    )
    db.add(user)
    return user


def save_user(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409) from None


def govern(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(23062402)"))


def session_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def revoke_sessions(db: Session, user_id: UUID) -> None:
    db.execute(delete(AdminSession).where(AdminSession.user_id == user_id))


def invalidate_access(db: Session, user: User) -> None:
    user.auth_version += 1
    user.updated_at = utc_now()
    revoke_sessions(db, user.id)


def require_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})


def get_user(db: Session, user_id: UUID, *, lock: bool = False) -> User | None:
    query = select(User).where(User.id == user_id)
    return db.scalar(query.with_for_update() if lock else query)
