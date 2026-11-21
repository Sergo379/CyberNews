from datetime import timedelta
from secrets import token_urlsafe
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select

from cybernews_runtime.audit import Limit, Offset, add_event, audit_query
from cybernews_runtime.contracts import AccountIdentity, PrincipalIdentity
from cybernews_runtime.security import (
    AccountStatus, AdminHeader, Db, Role, require_service_key, utc_now,
)

from .accounts import add_user, get_user, invalidate_access, nickname_key, require_password, revoke_sessions, save_user, session_hash
from .config import access_ttl, admin_ttl, internal_key
from .dependencies import Active, Administrator, Locked, SuperAdminWrite, get_principal, require_admin_role, require_admin_session
from .models import AdminSession, AuthAudit, User
from .passwords import hasher, verify_password
from .rate_limit import limit_attempt
from .schemas import (
    AccessResponse, AccountChange, AdminSessionView, AdminUnlockResponse, AuthAuditView, ChangePassword,
    Login, Profile, ProfileUpdate, Registration, RoleChange, SetAdminPassword, Unlock,
)
from .tokens import issue_token

public = APIRouter(tags=["accounts"])
admin = APIRouter(prefix="/admin", tags=["administration"])
internal = APIRouter(prefix="/internal/v1", include_in_schema=False)


@public.post("/register", response_model=Profile, status_code=201)
def register(data: Registration, db: Db):
    user = add_user(db, data)
    save_user(db)
    return user


@public.post("/login", response_model=AccessResponse)
def login(data: Login, db: Db, request: Request, response: Response):
    email = data.email.casefold()
    limit_attempt(request, "login", email)
    user = db.scalar(select(User).where(func.lower(User.email) == email).with_for_update())
    verified = verify_password(data.password.get_secret_value(), user.password_hash if user else None)
    if not verified or user is None or user.status != AccountStatus.ACTIVE:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    user.last_login_at = utc_now()
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password.get_secret_value())
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return AccessResponse(access_token=issue_token(user), expires_in=access_ttl)


@public.get("/me", response_model=Profile)
def me(principal: Active):
    return principal.user


@public.patch("/me", response_model=Profile)
def update_profile(data: ProfileUpdate, principal: Locked, db: Db):
    user = principal.user
    if data.email is not None:
        user.email = data.email.casefold()
    if data.nickname is not None:
        user.nickname = data.nickname
        user.nickname_key = nickname_key(data.nickname)
    user.updated_at = utc_now()
    save_user(db)
    return user


@public.post("/change-password", status_code=204)
def change_password(data: ChangePassword, principal: Locked, db: Db, request: Request):
    user = principal.user
    limit_attempt(request, "change-password", str(user.id))
    require_password(user, data.current_password.get_secret_value())
    new_password = data.new_password.get_secret_value()
    if verify_password(new_password, user.admin_password_hash) or verify_password(new_password, user.password_hash):
        raise HTTPException(400)
    user.password_hash = hasher.hash(new_password)
    invalidate_access(db, user)
    db.commit()


@admin.put("/password", status_code=204)
def set_admin_password(data: SetAdminPassword, principal: Locked, db: Db, request: Request):
    user = principal.user
    require_admin_role(user)
    limit_attempt(request, "admin-password", str(user.id))
    require_password(user, data.current_password.get_secret_value())
    password = data.admin_password.get_secret_value()
    if verify_password(password, user.password_hash):
        raise HTTPException(400)
    user.admin_password_hash = hasher.hash(password)
    revoke_sessions(db, user.id)
    add_event(db, AuthAudit, user.id, "admin_password_set", user.id)
    db.commit()


@admin.post("/unlock", response_model=AdminUnlockResponse)
def unlock(data: Unlock, principal: Locked, db: Db, request: Request, response: Response):
    user = principal.user
    require_admin_role(user)
    limit_attempt(request, "admin-unlock", str(user.id))
    if not verify_password(data.admin_password.get_secret_value(), user.admin_password_hash):
        add_event(db, AuthAudit, user.id, "admin_unlock", user.id, result="denied")
        db.commit()
        raise HTTPException(403)
    now = utc_now()
    expires = min(now + timedelta(seconds=admin_ttl), principal.claims.expires_at)
    if expires <= now:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    db.execute(delete(AdminSession).where(
        AdminSession.user_id == user.id, AdminSession.access_jti == principal.claims.jti,
    ))
    token = token_urlsafe(32)
    db.add(AdminSession(
        token_hash=session_hash(token), user_id=user.id, access_jti=principal.claims.jti, expires_at=expires,
    ))
    add_event(db, AuthAudit, user.id, "admin_unlock", user.id)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return AdminUnlockResponse(admin_session=token, expires_at=expires)


@admin.post("/lock", status_code=204)
def lock(principal: Locked, token: AdminHeader, db: Db):
    session = require_admin_session(db, principal, token)
    db.delete(session)
    add_event(db, AuthAudit, principal.user.id, "admin_lock", principal.user.id)
    db.commit()


@admin.get("/session", response_model=AdminSessionView)
def admin_session(principal: Active, token: AdminHeader, db: Db, response: Response):
    session = require_admin_session(db, principal, token)
    response.headers["Cache-Control"] = "no-store"
    return AdminSessionView(expires_at=session.expires_at)


@admin.get("/users", response_model=list[Profile])
def list_users(principal: Administrator, db: Db, limit: Limit = 50, offset: Offset = 0):
    if principal.user.role != Role.SUPER_ADMIN:
        raise HTTPException(403)
    return list(db.scalars(select(User).order_by(User.created_at, User.id).limit(limit).offset(offset)))


@admin.patch("/users/{user_id}/role", response_model=Profile)
def change_role(user_id: UUID, data: RoleChange, principal: SuperAdminWrite, db: Db):
    actor = principal.user
    if user_id == actor.id:
        raise HTTPException(403)
    target = get_user(db, user_id, lock=True)
    if target is None:
        raise HTTPException(404)
    if target.status != AccountStatus.ACTIVE:
        raise HTTPException(409)
    if target.role == data.role:
        return target
    previous_role = target.role
    target.role = data.role
    if data.role == Role.USER:
        target.admin_password_hash = None
    invalidate_access(db, target)
    revoked = data.role == Role.USER or previous_role == Role.SUPER_ADMIN
    event = add_event(
        db, AuthAudit, actor.id, "role_revoked" if revoked else "role_assigned",
        target.id, data.reason,
    )
    event.previous_role = previous_role
    event.new_role = data.role
    db.commit()
    return target


def change_status(db: Db, actor: User, target_id: UUID, status: AccountStatus, reason: str) -> User:
    target = get_user(db, target_id, lock=True)
    if target is None:
        raise HTTPException(404)
    if target.role != Role.USER:
        raise HTTPException(403)
    if target.status == status:
        raise HTTPException(409)
    target.status = status
    invalidate_access(db, target)
    action = "account_suspended" if status == AccountStatus.SUSPENDED else "account_restored"
    add_event(db, AuthAudit, actor.id, action, target.id, reason)
    db.commit()
    return target


@admin.post("/users/{user_id}/suspend", response_model=Profile)
def suspend(user_id: UUID, data: AccountChange, principal: SuperAdminWrite, db: Db):
    return change_status(db, principal.user, user_id, AccountStatus.SUSPENDED, data.reason)


@admin.post("/users/{user_id}/restore", response_model=Profile)
def restore(user_id: UUID, data: AccountChange, principal: SuperAdminWrite, db: Db):
    return change_status(db, principal.user, user_id, AccountStatus.ACTIVE, data.reason)


@admin.get("/audit", response_model=list[AuthAuditView])
def audit(principal: Administrator, db: Db, limit: Limit = 50, offset: Offset = 0):
    actor_id = None if principal.user.role == Role.SUPER_ADMIN else principal.user.id
    return list(db.scalars(audit_query(AuthAudit, actor_id, limit, offset)))


@internal.get("/principal", response_model=PrincipalIdentity)
def internal_principal(request: Request, db: Db, require_admin: bool = False):
    require_service_key(request, internal_key)
    scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(401)
    principal = get_principal(db, HTTPAuthorizationCredentials(scheme=scheme, credentials=credential))
    if require_admin:
        require_admin_session(db, principal, request.headers.get("X-Admin-Session"))
    return PrincipalIdentity.model_validate(principal.user, from_attributes=True)


@internal.get("/users/{user_id}", response_model=AccountIdentity)
def internal_user(user_id: UUID, request: Request, db: Db):
    require_service_key(request, internal_key)
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(404)
    return AccountIdentity.model_validate(user, from_attributes=True)
