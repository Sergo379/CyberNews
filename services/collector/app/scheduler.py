import logging
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from cybernews_runtime.logs import request_id
from cybernews_runtime.news import FeedBatch, ImportCounts, VersionedPolicy
from cybernews_runtime.security import utc_now

from .fetch import FeedError
from .models import RssSource, SourceRun, SyncRun
from .parse import parse_feed

logger = logging.getLogger("cybernews.rss")
SYNC_LOCK = 23062432


class SyncBusy(Exception):
    pass


def queue_run(db, trigger, source_id=None, actor_id=None):
    run = SyncRun(
        trigger=trigger, source_id=source_id, requested_by=actor_id,
        request_id=request_id.get() or uuid4().hex,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != "uq_sync_live_run":
            raise
        raise SyncBusy from None
    return run


@contextmanager
def coordinator(engine):
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK})
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK})
                    connection.commit()
                except SQLAlchemyError:
                    connection.invalidate()


class Scheduler:
    def __init__(self, database, fetcher, article_client, interval, auto_sync):
        self.database = database
        self.fetcher = fetcher
        self.article_client = article_client
        self.interval = interval
        self.auto_sync = auto_sync
        self.stopping = Event()
        self.wake = Event()
        self.thread = Thread(target=self.loop, name="rss-scheduler", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=25)

    def loop(self):
        next_run = monotonic()
        first_run = True
        while not self.stopping.is_set():
            try:
                with coordinator(self.database.engine) as acquired:
                    if acquired:
                        self.recover()
                        now = monotonic()
                        if self.auto_sync and now >= next_run:
                            try:
                                with self.database.sessions.begin() as db:
                                    queue_run(db, "startup" if first_run else "scheduled")
                            except SyncBusy:
                                pass
                            first_run = False
                            next_run = now + self.interval
                        self.run_queued()
            except Exception as exc:
                logger.error("RSS scheduler iteration failed", extra={"error_type": type(exc).__name__})
            self.wake.wait(2)
            self.wake.clear()

    def recover(self):
        with self.database.sessions.begin() as db:
            run = db.scalar(select(SyncRun).where(SyncRun.status == "running"))
            if run is None:
                return
            run.status = "interrupted"
            run.finished_at = utc_now()
            for item in db.scalars(select(SourceRun).where(SourceRun.run_id == run.id, SourceRun.status == "running")):
                item.status = "interrupted"
                item.error = "run_interrupted"
                item.finished_at = utc_now()
                source = db.get(RssSource, item.source_id)
                source.status = "error"
                source.last_error = "run_interrupted"

    def run_queued(self):
        with self.database.sessions(expire_on_commit=False) as db, db.begin():
            run = db.scalar(select(SyncRun).where(SyncRun.status == "queued").with_for_update())
            if run is None:
                return
            run.status = "running"
            run.started_at = utc_now()
            query = select(RssSource.id).where(RssSource.active).order_by(RssSource.created_at, RssSource.id)
            if run.source_id is not None:
                query = query.where(RssSource.id == run.source_id)
            source_ids = list(db.scalars(query))

        token = request_id.set(run.request_id)
        try:
            results = []
            for source_id in source_ids:
                if self.stopping.is_set():
                    break
                results.append(self.sync_source(run.id, source_id))
            if self.stopping.is_set():
                status = "interrupted"
            elif any(result in {"error", "partial"} for result in results):
                status = "failed" if all(result == "error" for result in results) else "partial"
            else:
                status = "completed"
            with self.database.sessions.begin() as db:
                stored = db.get(SyncRun, run.id)
                stored.status = status
                stored.finished_at = utc_now()
        finally:
            request_id.reset(token)

    def sync_source(self, run_id, source_id):
        with self.database.sessions(expire_on_commit=False) as db, db.begin():
            source = db.get(RssSource, source_id)
            source.last_attempt_at = utc_now()
            source.status = "running"
            db.add(SourceRun(run_id=run_id, source_id=source.id, status="running"))

        counts = ImportCounts()
        seen = skipped = 0
        result = None
        error = None
        status = "ok"
        try:
            result = self.fetcher.fetch(
                source.feed_url, etag=source.etag, last_modified=source.last_modified, validator_url=source.validator_url,
            )
            if result.body is None:
                if source.validator_url != result.url or not (source.etag or source.last_modified):
                    raise FeedError("unexpected_not_modified")
                status = "not_modified"
            else:
                entries, skipped = parse_feed(result.body, result.url, source)
                seen = len(entries) + skipped
                policy = VersionedPolicy.model_validate(source, from_attributes=True)
                for first in range(0, len(entries), 20):
                    if self.stopping.is_set():
                        raise FeedError("run_interrupted")
                    counts.add(self.article_client.ingest(FeedBatch(
                        source_id=source.id, source_name=source.name, source_url=source.website_url,
                        policy=policy, entries=entries[first:first + 20],
                    )))
                if counts.conflicted:
                    raise FeedError("article_identity_conflict")
        except FeedError as exc:
            error = str(exc)
            status = "error"
        except Exception as exc:
            logger.warning("RSS source processing failed", extra={"error_type": type(exc).__name__})
            status, error = "error", "feed_processing_error"

        with self.database.sessions.begin() as db:
            current = db.get(RssSource, source_id)
            item = db.get(SourceRun, (run_id, source_id))
            item.status = status
            item.error = error
            item.seen = seen
            item.skipped = skipped
            item.finished_at = utc_now()
            for field, value in counts.model_dump().items():
                setattr(item, field, value)

            current.status = status
            current.last_error = error
            current.processed_count += counts.created + counts.updated + counts.unchanged
            if status != "error":
                current.last_success_at = item.finished_at
                current.validator_url = result.url
                if status == "ok":
                    current.etag, current.last_modified = result.etag, result.last_modified
                else:
                    current.etag = result.etag or current.etag
                    current.last_modified = result.last_modified or current.last_modified
            current.updated_at = item.finished_at
        if error:
            logger.warning("RSS source %s failed: %s", source_id, error)
        else:
            logger.info("RSS source %s %s, received=%d created=%d updated=%d", source_id, status, seen, counts.created, counts.updated)
        if error and (counts.created or counts.updated or counts.unchanged):
            return "partial"
        return status
