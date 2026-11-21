from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, literal_column
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cybernews_runtime.audit import AuditFields


class Base(DeclarativeBase):
    """Auth Service metadata."""


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'moderator', 'super_admin')", name="ck_user_role"),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_user_status"),
        CheckConstraint("auth_version >= 1", name="ck_user_auth_version"),
        CheckConstraint("role <> 'user' OR admin_password_hash IS NULL", name="ck_user_admin_password"),
        Index("uq_users_email_ci", func.lower(literal_column("email")), unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320))
    nickname: Mapped[str] = mapped_column(String(32))
    nickname_key: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    admin_password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    auth_version: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    access_jti: Mapped[UUID]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateBucket(Base):
    __tablename__ = "auth_rate_buckets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthAudit(AuditFields, Base):
    __tablename__ = "auth_audit"
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    previous_role: Mapped[str | None] = mapped_column(String(16))
    new_role: Mapped[str | None] = mapped_column(String(16))
