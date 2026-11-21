from fastapi import APIRouter

from cybernews_runtime.admin_client import AdminClient
from cybernews_runtime.application import create_application

from .api import admin, internal, public
from .config import auth_key, auth_url, settings

client = AdminClient(auth_url, auth_key)
app = create_application("Article Service", settings, APIRouter(), "/api/v1/articles", shutdown=client.close)
app.state.admin_client = client
app.include_router(admin)
app.include_router(internal)
app.include_router(public)
