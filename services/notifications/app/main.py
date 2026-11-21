from fastapi import APIRouter

from cybernews_runtime.application import create_application
from cybernews_runtime.service_client import ArticleReader, IdentityClient

from .api import router
from .config import article_key, article_url, auth_key, auth_url, broker, settings
from .consumer import Consumer


def start():
    app.state.consumer.start()


def stop():
    app.state.consumer.stop()
    app.state.identity_client.close()
    app.state.article_reader.close()


def consumer_ready():
    return app.state.consumer.connected.is_set()


app = create_application(
    "Notification Service", settings, APIRouter(), "/api/v1/notifications",
    startup=start, shutdown=stop, dependency_check=consumer_ready, dependency_name="rabbitmq",
)
app.state.identity_client = IdentityClient(auth_url, auth_key)
app.state.article_reader = ArticleReader(article_url, article_key)
app.state.consumer = Consumer(broker, app.state.database)
app.include_router(router)
