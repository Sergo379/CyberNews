import logging
from datetime import timedelta

import pika
from sqlalchemy import func, select

from cybernews_runtime.broker import EXCHANGE, ROUTING_KEY, BrokerWorker
from cybernews_runtime.events import ArticlePublished
from cybernews_runtime.news import ArticleStatus
from cybernews_runtime.security import utc_now

from .models import ArticleOutbox

log = logging.getLogger("cybernews.outbox")


def record_first_publication(db, article):
    if article.status != ArticleStatus.PUBLISHED or article.ever_published:
        return
    article.ever_published = True
    db.add(ArticleOutbox(
        article_id=article.id, category=article.category, source_id=article.source_id,
        published_at=article.published_at, created_at=func.clock_timestamp(),
    ))


class Dispatcher(BrokerWorker):
    def __init__(self, broker, database):
        super().__init__(broker, "article outbox")
        self.database = database

    def serve(self, connection, channel):
        channel.confirm_delivery()
        while not self.stopping.is_set():
            if not self.dispatch_one(channel):
                connection.process_data_events(time_limit=1)

    def dispatch_one(self, channel):
        retry = False
        with self.database.sessions.begin() as db:
            row = db.scalar(select(ArticleOutbox).where(
                ArticleOutbox.delivered_at.is_(None), ArticleOutbox.next_attempt_at <= utc_now(),
            ).order_by(ArticleOutbox.next_attempt_at, ArticleOutbox.event_id).limit(1).with_for_update(skip_locked=True))
            if row is None:
                return False
            event = ArticlePublished(
                event_id=row.event_id, event_type=ROUTING_KEY, event_version=1,
                article_id=row.article_id, category=row.category, source_id=row.source_id,
                published_at=row.published_at, created_at=row.created_at,
            )
            try:
                channel.basic_publish(
                    exchange=EXCHANGE, routing_key=ROUTING_KEY,
                    body=event.model_dump_json().encode(),
                    properties=pika.BasicProperties(
                        message_id=str(row.event_id), content_type="application/json",
                        type=ROUTING_KEY, delivery_mode=2,
                    ),
                    mandatory=True,
                )
            except (pika.exceptions.AMQPError, OSError) as exc:
                row.attempts += 1
                row.next_attempt_at = utc_now() + timedelta(seconds=2 ** min(row.attempts, 6))
                log.warning("Article event remains in outbox", extra={"error_type": type(exc).__name__})
                retry = True
            else:
                row.delivered_at = utc_now()
        if retry and not channel.is_open:
            raise pika.exceptions.ChannelWrongStateError("Reconnect publisher")
        return True
