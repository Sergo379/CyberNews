import logging
from datetime import timedelta
from threading import Event, Thread
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from cybernews_runtime.audit import Limit, Offset, add_event
from cybernews_runtime.community import ModerationAction, ModerationInstruction, ModerationResult, ReviewComment
from cybernews_runtime.logs import request_id
from cybernews_runtime.security import Db, utc_now

from .auth_client import Administrator, SuperAdmin
from .models import CommentCommand, ModerationAudit
from .schemas import RestrictionLift

router = APIRouter(prefix="/comments", tags=["comment moderation"])
log = logging.getLogger("cybernews.comment_moderation")
CommandKey = Annotated[UUID | None, Header(alias="Idempotency-Key")]


class CommandWorker:
    def __init__(self, database, community):
        self.database = database
        self.community = community
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="comment-moderation", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=12)

    def run(self):
        while not self.stopping.is_set():
            try:
                done = self.process()
            except Exception as exc:
                log.warning("Comment command deferred", extra={"error_type": type(exc).__name__})
                done = False
            if not done:
                self.stopping.wait(1)

    def process(self, command_id: UUID | None = None):
        with self.database.sessions.begin() as db:
            query = select(CommentCommand).where(CommentCommand.state == "pending")
            if command_id is None:
                query = query.where(CommentCommand.next_attempt_at <= utc_now())
            else:
                query = query.where(CommentCommand.id == command_id)
            command = db.scalar(query.order_by(
                CommentCommand.next_attempt_at, CommentCommand.id,
            ).limit(1).with_for_update(skip_locked=True))
            if command is None:
                return False
            token = request_id.set(command.request_id)
            try:
                self.deliver(db, command)
            finally:
                request_id.reset(token)
        return True

    def deliver(self, db, command):
        data = ModerationInstruction(
            command_id=command.id, action=command.action, actor_id=command.actor_id,
            actor_role=command.actor_role, reason=command.reason,
        )
        try:
            result = self.community.model(
                ModerationResult, "POST", f"/internal/v1/review/comments/{command.comment_id}/commands",
                payload=data.model_dump(mode="json"), expected_errors=(403, 404, 409),
            )
            if (result.id != command.id or result.comment_id != command.comment_id or
                    result.actor_id != command.actor_id or result.action != command.action):
                raise HTTPException(503)
        except HTTPException as exc:
            if exc.status_code in {403, 404, 409}:
                command.state = "rejected"
                command.error_status = exc.status_code
            else:
                command.attempts += 1
                command.next_attempt_at = utc_now() + timedelta(seconds=2 ** min(command.attempts, 6))
            return

        command.state = "completed"
        command.result = result.model_dump(mode="json")
        add_event(
            db, ModerationAudit, command.actor_id, "comment_hidden" if command.action == "hide" else "comment_restored",
            command.comment_id, command.reason, result=result.result,
        )


def submit(db, worker, actor, comment_id, action: ModerationAction, reason, key):
    command_id = key or uuid4()
    db.execute(insert(CommentCommand).values(
        id=command_id, comment_id=comment_id, actor_id=actor.id, actor_role=actor.role, action=action,
        reason=reason, request_id=request_id.get() or uuid4().hex,
        next_attempt_at=utc_now() + timedelta(seconds=3),
    ).on_conflict_do_nothing())
    saved = db.get(CommentCommand, command_id)
    if (saved.actor_id, saved.comment_id, saved.action, saved.reason) != (actor.id, comment_id, action, reason):
        raise HTTPException(409)
    db.commit()
    try:
        worker.process(command_id)
    except Exception as exc:
        log.warning("Comment command deferred", extra={"error_type": type(exc).__name__})
    saved = db.get(CommentCommand, command_id, populate_existing=True)
    if saved.state == "rejected":
        raise HTTPException(saved.error_status)
    if saved.state == "pending":
        raise HTTPException(503, headers={"Retry-After": "2", "Idempotency-Key": str(command_id)})
    return ModerationResult.model_validate(saved.result)


@router.get("", response_model=list[ReviewComment])
def review_comments(_: Administrator, request: Request, article_id: UUID | None = None,
                    limit: Limit = 50, offset: Offset = 0):
    path = f"/internal/v1/review/comments?limit={limit}&offset={offset}"
    if article_id is not None:
        path += f"&article_id={article_id}"
    return request.app.state.community.models(ReviewComment, "GET", path)


@router.get("/{comment_id}", response_model=ReviewComment)
def review_comment(comment_id: UUID, _: Administrator, request: Request):
    return request.app.state.community.model(
        ReviewComment, "GET", f"/internal/v1/review/comments/{comment_id}", expected_errors=(404,),
    )


@router.get("/{comment_id}/history", response_model=list[ModerationResult])
def history(comment_id: UUID, _: SuperAdmin, request: Request, limit: Limit = 50, offset: Offset = 0):
    return request.app.state.community.models(
        ModerationResult, "GET", f"/internal/v1/review/comments/{comment_id}/history?limit={limit}&offset={offset}",
        expected_errors=(404,),
    )


@router.post("/{comment_id}/hide", response_model=ModerationResult)
def hide(comment_id: UUID, data: RestrictionLift, actor: Administrator, db: Db, request: Request,
         key: CommandKey = None):
    return submit(db, request.app.state.command_worker, actor, comment_id, "hide", data.reason, key)


@router.post("/{comment_id}/restore", response_model=ModerationResult)
def restore(comment_id: UUID, data: RestrictionLift, actor: SuperAdmin, db: Db, request: Request,
            key: CommandKey = None):
    return submit(db, request.app.state.command_worker, actor, comment_id, "restore", data.reason, key)
