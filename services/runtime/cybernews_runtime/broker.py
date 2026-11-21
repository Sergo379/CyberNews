import logging
import os
from dataclasses import dataclass, field
from threading import Event, Thread

import pika

EXCHANGE = "cybernews.events"
ROUTING_KEY = "article.published"
QUEUE = "cybernews.notifications.article-published.v1"
DEAD_EXCHANGE = "cybernews.dead"
DEAD_QUEUE = "cybernews.notifications.dead.v1"
DEAD_KEY = "notifications.article-published.v1"
MAX_DELIVERIES = 5
log = logging.getLogger("cybernews.rabbitmq")
logging.getLogger("pika").setLevel(logging.WARNING)


@dataclass(frozen=True)
class Broker:
    host: str
    vhost: str
    user: str
    password: str = field(repr=False)

    @classmethod
    def from_env(cls):
        password = os.getenv("RABBITMQ_PASSWORD")
        if not password:
            raise ValueError("RABBITMQ_PASSWORD is required")
        return cls(
            os.getenv("RABBITMQ_HOST", "rabbitmq"), os.getenv("RABBITMQ_VHOST", "cybernews"),
            os.getenv("RABBITMQ_USER", "cybernews"), password,
        )

    def connect(self):
        params = pika.ConnectionParameters(
            host=self.host, port=5672, virtual_host=self.vhost,
            credentials=pika.PlainCredentials(self.user, self.password),
            connection_attempts=1, socket_timeout=3, stack_timeout=7,
            blocked_connection_timeout=5, heartbeat=20,
        )
        return pika.BlockingConnection(params)


def declare_topology(channel):
    channel.exchange_declare(EXCHANGE, "topic", durable=True)
    channel.exchange_declare(DEAD_EXCHANGE, "direct", durable=True)
    channel.queue_declare(DEAD_QUEUE, durable=True)
    channel.queue_bind(DEAD_QUEUE, DEAD_EXCHANGE, DEAD_KEY)
    channel.queue_declare(QUEUE, durable=True, arguments={
        "x-queue-type": "quorum",
        "x-delivery-limit": MAX_DELIVERIES,
        "x-dead-letter-exchange": DEAD_EXCHANGE,
        "x-dead-letter-routing-key": DEAD_KEY,
    })
    channel.queue_bind(QUEUE, EXCHANGE, ROUTING_KEY)


class BrokerWorker:
    def __init__(self, broker, name):
        self.broker = broker
        self.name = name
        self.stopping = Event()
        self.connected = Event()
        self.thread = Thread(target=self.run, name=name, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=20)

    def run(self):
        while not self.stopping.is_set():
            try:
                with self.broker.connect() as connection:
                    channel = connection.channel()
                    declare_topology(channel)
                    self.connected.set()
                    log.info("%s connected", self.name)
                    self.serve(connection, channel)
            except Exception as exc:
                log.warning("%s interrupted", self.name, extra={"error_type": type(exc).__name__})
            finally:
                self.connected.clear()
            self.stopping.wait(2)
