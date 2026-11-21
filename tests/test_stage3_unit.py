import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "runtime"))

from cybernews_runtime.news import ContentMode, SourcePolicy, url_key
from services.articles.app.classification import classify
from services.articles.app.content import clean_content
from services.collector.app.fetch import FeedError, FeedFetcher
from services.collector.app.parse import parse_feed

FIXTURES = ROOT / "tests" / "fixtures" / "stage3"
HOSTS = frozenset({"rss-fixture.example", "redirect-fixture.example"})
URL = "https://rss-fixture.example/feed"


@pytest.fixture
def source():
    return SimpleNamespace(language="en", content_policy=ContentMode.EXTERNAL, allow_images=False)


def records(*addresses):
    def resolve(_host, port, *, type):
        return [(socket.AF_INET, type, 0, "", (address, port)) for address in addresses]
    return resolve


def fetcher(handler, resolver=None, limit=1024):
    return FeedFetcher(
        HOSTS, limit, resolver=resolver or records("93.184.215.14"),
        transport_factory=lambda: httpx.MockTransport(handler),
    )


def test_valid_rss_preserves_original_link_and_date(source):
    items, skipped = parse_feed((FIXTURES / "news.rss").read_bytes(), URL, source)
    assert skipped == 0 and len(items) == 2
    assert items[0].published_at == datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc)
    assert items[0].original_url.endswith("?variant=stable&utm_source=feed")
    assert items[0].external_guid == "fixture-acorn" and items[0].language == "en-us"
    assert "Vulnerabilities" in items[0].tags
    assert items[0].content is None and items[0].image_url is None


def test_optional_fields_and_unknown_date(source):
    item = parse_feed((FIXTURES / "news.rss").read_bytes(), URL, source)[0][1]
    assert all(getattr(item, field) is None for field in ("author", "summary", "image_url", "published_at"))


def test_atom_date_and_author(source):
    item = parse_feed((FIXTURES / "news.atom").read_bytes(), URL, source)[0][0]
    assert item.published_at == datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
    assert item.original_url.endswith("/story/dogwood") and item.author == "Fixture editor"


@pytest.mark.parametrize("body", [b"<rss><unclosed>", b"<!DOCTYPE rss><rss version='2.0'/>"])
def test_invalid_xml_rejected(source, body):
    with pytest.raises(FeedError, match="invalid_feed_xml"):
        parse_feed(body, URL, source)


@pytest.mark.parametrize("response", [
    httpx.Response(429), httpx.Response(503),
])
def test_http_error_reported(response):
    with pytest.raises(FeedError, match=f"feed_http_{response.status_code}"):
        fetcher(lambda _: response).fetch(URL)


def test_connection_failure_reported():
    def fail(_):
        raise httpx.ConnectError("unavailable")
    with pytest.raises(FeedError, match="feed_connection_error"):
        fetcher(fail).fetch(URL)


def test_rss_read_timeout_is_reported():
    def fail(_):
        raise httpx.ReadTimeout("fixture did not reply")

    with pytest.raises(FeedError, match="feed_timeout"):
        fetcher(fail).fetch(URL)


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "2049"}])
def test_response_limit(headers):
    with pytest.raises(FeedError, match="feed_too_large"):
        fetcher(lambda _: httpx.Response(200, content=b"x" * 2049, headers=headers)).fetch(URL)


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["::1"],
    ["::ffff:127.0.0.1"], ["93.184.215.14", "192.168.1.1"],
])
def test_denies_nonpublic_dns_answers_without_opening_connection(addresses):
    with pytest.raises(FeedError, match="blocked_feed_ip"):
        fetcher(lambda _: pytest.fail("No connection expected"), records(*addresses)).fetch(URL)


@pytest.mark.parametrize("url", [
    "file:///tmp/fixture", "https://localhost/feed", "https://rss-fixture.example:8443/feed",
    "http://user@rss-fixture.example/feed", "https://rss-fixture.example\\invalid",
])
def test_rejects_nonapproved_urls(url):
    with pytest.raises(FeedError):
        fetcher(lambda _: pytest.fail("No connection expected")).fetch(url)


def test_redirect_validates_destination_and_pins_tls_hostname():
    def handler(request):
        assert request.url.host == "93.184.215.14"
        assert request.extensions["sni_hostname"] == "rss-fixture.example"
        return httpx.Response(301, headers={"location": "https://redirect-fixture.example/feed"})

    def resolve(host, port, *, type):
        return records("93.184.215.14" if host == "rss-fixture.example" else "127.0.0.1")(host, port, type=type)

    with pytest.raises(FeedError, match="blocked_feed_ip"):
        fetcher(handler, resolve).fetch(URL)


def test_conditional_requests_only_for_matching_address():
    calls = []

    def handler(request):
        calls.append((request.headers["Host"], request.headers.get("If-None-Match")))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": "https://redirect-fixture.example/final"})
        return httpx.Response(304)

    final = "https://redirect-fixture.example/final"
    assert fetcher(handler).fetch(URL, etag='"x"', validator_url=final).body is None
    assert calls == [("rss-fixture.example", None), ("redirect-fixture.example", '"x"')]


def test_tracking_keys_only_are_removed():
    changed = url_key("https://NEWS.example:443/items/1?tag=z&tag=x&utm_source=feed&tag=%2F#details")
    assert changed == "https://news.example/items/1?tag=z&tag=x&tag=%2F#details"


@pytest.mark.parametrize(("title", "category"), [
    ("CVE-2026-1234 in a switch", "vulnerabilities"), ("Ransomware interrupts a firm", "malware"),
    ("Database breach announced", "data-breaches"), ("New DDOS campaign", "cyberattacks"),
    ("Security research report", "research"), ("Secure coding guidelines", "software-security"),
    ("Quarterly information", "other"),
])
def test_classification(title, category):
    assert classify(title, None, []) == category


def test_approved_html_keeps_structure_and_removes_unsafe_markup(source):
    source.content_policy = ContentMode.FULL
    source.allow_images = True
    item = parse_feed((FIXTURES / "news.rss").read_bytes(), URL, source)[0][0]
    html = clean_content(item.content, allow_images=False)
    assert "<h2>Test Full Heading</h2>" in html and "<p>Test full article section.</p>" in html
    assert "script" not in html and item.image_url.endswith("/images/acorn.jpg")


def test_rights_evidence_required():
    with pytest.raises(ValueError):
        SourcePolicy(content_policy=ContentMode.FULL)
