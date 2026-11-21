from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from cybernews_runtime.audit import AuditView, Limit, Offset, add_event, audit_query
from cybernews_runtime.contracts import AccountIdentity
from cybernews_runtime.security import AccountStatus, Db, Role, require_service_key, utc_now

from .auth_client import Active, Administrator, Auth, SuperAdmin
from .config import internal_key
from .models import ModerationAudit, Report, Restriction
from .schemas import (
    CommentPermission, ReportCreate, ReportReview, ReportStatus, ReportView,
    RestrictionCreate, RestrictionLift, RestrictionView, Stats, TargetType,
)

restrictions = APIRouter(tags=["comment restrictions"])
reports = APIRouter(prefix="/reports", tags=["reports"])
admin = APIRouter(prefix="/admin", tags=["moderation audit"])
internal = APIRouter(prefix="/internal/v1", include_in_schema=False)


def permission(identity: AccountIdentity, db: Db) -> CommentPermission:
    if identity.status != AccountStatus.ACTIVE:
        return CommentPermission(user_id=identity.id, allowed=False, reason="account_suspended")
    restricted = db.scalar(select(Restriction.id).where(
        Restriction.user_id == identity.id, Restriction.active,
    )) is not None
    return CommentPermission(
        user_id=identity.id, allowed=not restricted, reason="comment_restricted" if restricted else "allowed",
    )


@restrictions.get("/comment-permission", response_model=CommentPermission)
def check_own_permission(identity: Active, db: Db):
    return permission(identity, db)


@internal.get("/comment-permission/{user_id}", response_model=CommentPermission)
def check_permission(user_id: UUID, request: Request, auth: Auth, db: Db):
    require_service_key(request, internal_key)
    return permission(auth.user(user_id), db)


@restrictions.post("/restrictions", response_model=RestrictionView, status_code=201)
def restrict(data: RestrictionCreate, actor: Administrator, auth: Auth, db: Db):
    target = auth.user(data.user_id)
    if actor.role == Role.MODERATOR and target.role != Role.USER:
        raise HTTPException(403)
    restriction = Restriction(user_id=target.id, created_by=actor.id, reason=data.reason)
    db.add(restriction)
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409) from None
    add_event(db, ModerationAudit, actor.id, "comment_restricted", restriction.id, data.reason)
    db.commit()
    return restriction


def restriction_query(limit, offset):
    return select(Restriction).order_by(Restriction.created_at.desc(), Restriction.id.desc()).limit(limit).offset(offset)


@restrictions.get("/restrictions", response_model=list[RestrictionView])
def list_restrictions(_: Administrator, db: Db, active: bool | None = None, limit: Limit = 50, offset: Offset = 0):
    query = restriction_query(limit, offset)
    if active is not None:
        query = query.where(Restriction.active == active)
    return list(db.scalars(query))


@restrictions.get("/users/{user_id}/restrictions", response_model=list[RestrictionView])
def user_restrictions(user_id: UUID, _: Administrator, auth: Auth, db: Db, limit: Limit = 50, offset: Offset = 0):
    auth.user(user_id)
    return list(db.scalars(restriction_query(limit, offset).where(Restriction.user_id == user_id)))


@restrictions.post("/restrictions/{restriction_id}/lift", response_model=RestrictionView)
def lift(restriction_id: UUID, data: RestrictionLift, actor: SuperAdmin, db: Db):
    restriction = db.get(Restriction, restriction_id, with_for_update=True)
    if restriction is None:
        raise HTTPException(404)
    if not restriction.active:
        raise HTTPException(409)
    restriction.active = False
    restriction.lifted_at = utc_now()
    restriction.lifted_by = actor.id
    add_event(db, ModerationAudit, actor.id, "comment_restriction_lifted", restriction.id, data.reason)
    db.commit()
    return restriction


@reports.post("", response_model=ReportView, status_code=201)
def create_report(data: ReportCreate, actor: Active, auth: Auth, db: Db):
    if data.target_type == TargetType.USER:
        auth.user(data.target_id)
    report = Report(author_id=actor.id, **data.model_dump())
    db.add(report)
    db.commit()
    return report


@reports.get("", response_model=list[ReportView])
def list_reports(_: Administrator, db: Db, status: ReportStatus | None = None, limit: Limit = 50, offset: Offset = 0):
    query = select(Report).order_by(Report.created_at.desc(), Report.id.desc()).limit(limit).offset(offset)
    if status is not None:
        query = query.where(Report.status == status)
    return list(db.scalars(query))


@reports.get("/{report_id}", response_model=ReportView)
def get_report(report_id: UUID, _: Administrator, db: Db):
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404)
    return report


@reports.patch("/{report_id}", response_model=ReportView)
def review_report(report_id: UUID, data: ReportReview, actor: Administrator, db: Db):
    report = db.get(Report, report_id, with_for_update=True)
    if report is None:
        raise HTTPException(404)
    if report.status != ReportStatus.PENDING:
        raise HTTPException(409)
    report.status = data.status
    report.reviewed_by = actor.id
    report.reviewed_at = utc_now()
    add_event(db, ModerationAudit, actor.id, f"report_{data.status}", report.id, data.reason)
    db.commit()
    return report


@admin.get("/audit", response_model=list[AuditView])
def audit(actor: Administrator, db: Db, limit: Limit = 50, offset: Offset = 0):
    actor_id = None if actor.role == Role.SUPER_ADMIN else actor.id
    return list(db.scalars(audit_query(ModerationAudit, actor_id, limit, offset)))


@admin.get("/stats", response_model=Stats)
def stats(actor: Administrator, db: Db):
    query = select(ModerationAudit.action, func.count()).group_by(ModerationAudit.action)
    if actor.role == Role.MODERATOR:
        query = query.where(ModerationAudit.actor_id == actor.id)
    return Stats(actions={name: total for name, total in db.execute(query)})
