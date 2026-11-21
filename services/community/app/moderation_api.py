from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from cybernews_runtime.audit import Limit, Offset
from cybernews_runtime.community import CommentTarget, ModerationInstruction, ModerationResult, ReviewComment
from cybernews_runtime.logs import request_id
from cybernews_runtime.security import AccountStatus, Db, Role, require_service_key, utc_now
from cybernews_runtime.service_client import Articles

from .api import published_comment
from .config import moderation_key
from .models import Comment, CommentModeration


def require_moderation(request: Request):
    require_service_key(request, moderation_key)


internal = APIRouter(prefix="/internal/v1", include_in_schema=False, dependencies=[Depends(require_moderation)])


@internal.get("/comments/{comment_id}/target", response_model=CommentTarget)
def report_target(comment_id: UUID, db: Db, articles: Articles):
    row = published_comment(db, articles, comment_id)
    return CommentTarget(id=row.id, article_id=row.article_id, author_id=row.author_id, status=row.status)


@internal.get("/review/comments", response_model=list[ReviewComment])
def review_comments(db: Db, article_id: UUID | None = None, limit: Limit = 50, offset: Offset = 0):
    query = select(Comment).order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit).offset(offset)
    if article_id is not None:
        query = query.where(Comment.article_id == article_id)
    return list(db.scalars(query))


@internal.get("/review/comments/{comment_id}", response_model=ReviewComment)
def review_comment(comment_id: UUID, db: Db):
    row = db.get(Comment, comment_id)
    if row is None:
        raise HTTPException(404)
    return row


@internal.get("/review/comments/{comment_id}/history", response_model=list[ModerationResult])
def history(comment_id: UUID, db: Db, limit: Limit = 50, offset: Offset = 0):
    if db.get(Comment, comment_id) is None:
        raise HTTPException(404)
    return list(db.scalars(select(CommentModeration).where(CommentModeration.comment_id == comment_id)
                           .order_by(CommentModeration.created_at.desc(), CommentModeration.id.desc())
                           .limit(limit).offset(offset)))


@internal.post("/review/comments/{comment_id}/commands", response_model=ModerationResult)
def moderate_comment(comment_id: UUID, data: ModerationInstruction, request: Request, db: Db):
    comment = db.get(Comment, comment_id, with_for_update=True)
    if comment is None:
        raise HTTPException(404)
    previous = db.get(CommentModeration, data.command_id)
    if previous is not None:
        if (previous.comment_id, previous.actor_id, previous.actor_role, previous.action, previous.reason) != (
            comment_id, data.actor_id, data.actor_role, data.action, data.reason,
        ):
            raise HTTPException(409)
        return previous

    identity = request.app.state.identity_client
    actor = identity.account(data.actor_id)
    if actor.status != AccountStatus.ACTIVE or actor.role != data.actor_role:
        raise HTTPException(403)
    if data.action == "restore" and actor.role != Role.SUPER_ADMIN:
        raise HTTPException(403)
    if actor.role == Role.MODERATOR and identity.account(comment.author_id).role != Role.USER:
        raise HTTPException(403)
    if comment.status == "deleted":
        raise HTTPException(409)

    target_status = "hidden" if data.action == "hide" else "published"
    result = "no_change"
    if comment.status != target_status:
        result = "applied"
        comment.status = target_status
        comment.updated_at = utc_now()
        comment.removed_at = comment.updated_at if target_status == "hidden" else None
        comment.moderated_by, comment.moderation_reason = actor.id, data.reason

    record = CommentModeration(
        id=data.command_id, comment_id=comment_id, actor_id=actor.id, actor_role=actor.role, action=data.action,
        reason=data.reason, result=result, status=target_status, request_id=request_id.get() or uuid4().hex,
    )
    db.add(record)
    db.commit()
    return record
