"""Run the Collector with controlled HTTP responses on the disposable test stack."""

import socket
import sys
from pathlib import Path
from time import sleep

import httpx
import uvicorn

sys.path.insert(0, "/srv")

from app.config import allowed_hosts, max_bytes
from app.fetch import FeedFetcher
from app.main import app
from cybernews_runtime.migration import upgrade_schema

FIXTURES = Path(__file__).parent / "fixtures" / "stage3"


def resolve(_host, port, *, type):
    return [(socket.AF_INET, type, 0, "", ("93.184.215.14", port))]


def respond(request):
    name = request.headers["Host"]
    path = request.url.path
    if name == "krebsonsecurity.com":
        return httpx.Response(200, content=b"<rss><unclosed>")
    if name == "www.bleepingcomputer.com":
        return httpx.Response(200, content=(FIXTURES / "news.atom").read_bytes())
    if name == "feeds.feedburner.com":
        if request.headers.get("If-None-Match") == '"acorn"':
            return httpx.Response(304)
        return httpx.Response(200, headers={"ETag": '"acorn"'}, content=(FIXTURES / "news.rss").read_bytes())
    if path == "/busy":
        sleep(1.0)
    if path == "/down":
        return httpx.Response(502)
    raw = (FIXTURES / "news.rss").read_bytes()
    if path == "/changed":
        raw = raw.replace(b"Acorn vulnerability check", b"Acorn vulnerability updated")
    elif path == "/licensed":
        raw = raw.replace(b"/story/acorn", b"/story/licensed").replace(b"fixture-acorn", b"licensed-acorn")
    return httpx.Response(200, content=raw)


if __name__ == "__main__":
    app.state.scheduler.fetcher = FeedFetcher(
        allowed_hosts, max_bytes, resolver=resolve, transport_factory=lambda: httpx.MockTransport(respond),
    )
    upgrade_schema()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)
