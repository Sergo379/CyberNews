from fastapi import APIRouter

from cybernews_runtime.admin_client import AdminClient
from cybernews_runtime.application import create_application

from .api import admin, internal, public
from .config import auth_key, auth_url, broker, settings
from .outbox import Dispatcher

def start():
    app.state.dispatcher.start()


def stop():
    app.state.dispatcher.stop()
    app.state.admin_client.close()


app = create_application(
    "Article Service", settings, APIRouter(), "/api/v1/articles", startup=start, shutdown=stop,
)
app.state.admin_client = AdminClient(auth_url, auth_key)
app.state.dispatcher = Dispatcher(broker, app.state.database)
app.include_router(admin)
app.include_router(internal)
app.include_router(public)
