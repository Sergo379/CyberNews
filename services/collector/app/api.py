from hashlib import sha256
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from cybernews_runtime.admin_client import SuperAdmin
from cybernews_runtime.audit import AuditView, Limit, Offset, add_event, audit_query
from cybernews_runtime.news import ContentMode, SourcePolicy, VersionedPolicy
from cybernews_runtime.security import Db, utc_now

from .config import allowed_hosts
from .fetch import FeedError, validated_host
from .models import CollectorAudit, RssSource, SourceRun, SyncRun
from .scheduler import SYNC_LOCK, SyncBusy, queue_run
from .schemas import RunDetail, RunView, SourceCreate, SourcePatch, SourceRunView, SourceView, StatusView

router = APIRouter(tags=["RSS administration"])


def feed_key(url: str) -> str:
    try:
        validated_host(url, allowed_hosts)
        normalized = str(httpx.URL(url))
    except (FeedError, httpx.InvalidURL):
        raise HTTPException(422) from None
    return sha256(normalized.encode()).hexdigest()


def commit_unique(db):
    try:
        db.commit()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409) from None


@router.get("/sources", response_model=list[SourceView])
def sources(_: SuperAdmin, db: Db, limit: Limit = 50, offset: Offset = 0):
    query = select(RssSource).order_by(RssSource.name, RssSource.id).limit(limit).offset(offset)
    return list(db.scalars(query))


@router.post("/sources", response_model=SourceView, status_code=201)
def create_source(data: SourceCreate, actor: SuperAdmin, db: Db):
    source = RssSource(**data.model_dump(), feed_key=feed_key(data.feed_url))
    db.add(source)
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409) from None
    add_event(db, CollectorAudit, actor.id, "rss_source_created", source.id)
    db.commit()
    return source


@router.patch("/sources/{source_id}", response_model=SourceView)
def update_source(source_id: UUID, data: SourcePatch, actor: SuperAdmin, db: Db, request: Request):
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": SYNC_LOCK}):
        raise HTTPException(409)
    source = db.get(RssSource, source_id, with_for_update=True)
    if source is None:
        raise HTTPException(404)
    changes = data.model_dump(exclude_unset=True)
    previous = SourcePolicy.model_validate(source, from_attributes=True)
    if "feed_url" in changes:
        changes["feed_key"] = feed_key(changes["feed_url"])
        if changes["feed_url"] != source.feed_url and (
            previous.content_policy == ContentMode.FULL or previous.allow_images
        ) and changes.get("rights_reference") in {None, previous.rights_reference}:
            changes.update(content_policy=ContentMode.EXTERNAL, rights_reference=None, allow_images=False)
    values = previous.model_dump()
    values.update({name: value for name, value in changes.items() if name in values})
    try:
        policy = SourcePolicy.model_validate(values)
    except ValidationError:
        raise HTTPException(422) from None

    for field, value in changes.items():
        setattr(source, field, value)
    if changes.keys() - {"active"}:
        source.etag = source.last_modified = source.validator_url = None
    source.updated_at = utc_now()
    if policy != previous:
        source.revision += 1
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409) from None
    if policy != previous:
        try:
            request.app.state.article_client.policy(source_id, VersionedPolicy(revision=source.revision, **values))
        except FeedError as exc:
            raise HTTPException(409 if str(exc) == "article_policy_conflict" else 503) from None
    add_event(db, CollectorAudit, actor.id, "rss_source_updated", source.id)
    commit_unique(db)
    return source


def schedule(request, db, actor, source_id=None):
    if source_id is not None:
        source = db.get(RssSource, source_id)
        if source is None:
            raise HTTPException(404)
        if not source.active:
            raise HTTPException(409)
    try:
        run = queue_run(db, "manual", source_id, actor.id)
    except SyncBusy:
        raise HTTPException(409) from None
    add_event(db, CollectorAudit, actor.id, "rss_sync_requested", run.id)
    db.commit()
    request.app.state.scheduler.wake.set()
    return run


@router.post("/sources/{source_id}/sync", response_model=RunView, status_code=202)
def sync_source(source_id: UUID, actor: SuperAdmin, db: Db, request: Request):
    return schedule(request, db, actor, source_id)


@router.post("/sync", response_model=RunView, status_code=202)
def sync_all(actor: SuperAdmin, db: Db, request: Request):
    return schedule(request, db, actor)


@router.get("/runs", response_model=list[RunView])
def runs(_: SuperAdmin, db: Db, limit: Limit = 20, offset: Offset = 0):
    query = select(SyncRun).order_by(SyncRun.created_at.desc(), SyncRun.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(query))


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_status(run_id: UUID, _: SuperAdmin, db: Db):
    run = db.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(404)
    source_runs = db.scalars(select(SourceRun).where(SourceRun.run_id == run_id).order_by(SourceRun.started_at))
    return RunDetail(
        **RunView.model_validate(run).model_dump(), sources=[SourceRunView.model_validate(item) for item in source_runs],
    )


@router.get("/status", response_model=StatusView)
def status(_: SuperAdmin, db: Db, request: Request):
    scheduler = request.app.state.scheduler
    query = select(SyncRun).order_by(SyncRun.created_at.desc(), SyncRun.id.desc()).limit(1)
    return {
        "auto_sync": scheduler.auto_sync, "interval_seconds": scheduler.interval,
        "active_sources": db.scalar(select(func.count()).select_from(RssSource).where(RssSource.active)),
        "last_run": db.scalar(query),
    }


@router.get("/admin/audit", response_model=list[AuditView])
def audit(_: SuperAdmin, db: Db, limit: Limit = 50, offset: Offset = 0):
    return list(db.scalars(audit_query(CollectorAudit, None, limit, offset)))
