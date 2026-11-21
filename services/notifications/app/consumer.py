import logging

from pydantic import ValidationError
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from cybernews_runtime.broker import MAX_DELIVERIES, QUEUE, ROUTING_KEY, BrokerWorker
from cybernews_runtime.events import ArticlePublished

from .models import Notification, ProcessedEvent, Subscription

log = logging.getLogger("cybernews.notifications")


def store_event(db, event):
    recorded = db.scalar(insert(ProcessedEvent).values(
        event_id=event.event_id, article_id=event.article_id, category=event.category, event_created_at=event.created_at,
    ).on_conflict_do_nothing().returning(ProcessedEvent.event_id))
    if recorded is None:
        return False
    recipients = select(
        func.gen_random_uuid(), Subscription.user_id, literal(event.article_id),
        literal(event.event_id), literal(event.category),
    ).where(Subscription.category == event.category, Subscription.created_at <= event.created_at)
    db.execute(insert(Notification).from_select(
        ["id", "user_id", "article_id", "event_id", "category"], recipients, include_defaults=False,
    ).on_conflict_do_nothing(constraint="uq_notification_user_event"))
    return True


class Consumer(BrokerWorker):
    def __init__(self, broker, database):
        super().__init__(broker, "article notification consumer")
        self.database = database

    def serve(self, _connection, channel):
        channel.basic_qos(prefetch_count=1)
        for method, properties, body in channel.consume(QUEUE, inactivity_timeout=1, auto_ack=False):
            if self.stopping.is_set():
                return
            if method is not None:
                self.handle(channel, method.delivery_tag, properties, body)

    def handle(self, channel, tag, properties, body):
        try:
            if not body or len(body) > 8192 or properties.content_type != "application/json":
                raise ValueError("Invalid message envelope")
            event = ArticlePublished.model_validate_json(body)
            if properties.type != ROUTING_KEY or properties.message_id != str(event.event_id):
                raise ValueError("Invalid message identity")
        except (ValidationError, ValueError):
            log.warning("Invalid article event moved to dead-letter queue")
            channel.basic_reject(tag, requeue=False)
            return

        try:
            with self.database.sessions.begin() as db:
                inserted = store_event(db, event)
        except SQLAlchemyError as exc:
            count = (properties.headers or {}).get("x-delivery-count", 0)
            count = count if isinstance(count, int) else 0
            retry = count < MAX_DELIVERIES - 1
            log.warning("Notification transaction deferred" if retry else "Notification event dead-lettered",
                        extra={"error_type": type(exc).__name__})
            if retry and self.stopping.wait(2 ** min(count, 3)):
                return
            channel.basic_reject(tag, requeue=retry)
            return

        channel.basic_ack(tag)
        if inserted:
            log.info("Article publication event recorded")
