import re
from calendar import timegm
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin
from xml.etree.ElementTree import ParseError

import feedparser
import nh3
from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException
from pydantic import ValidationError

from cybernews_runtime.news import ContentMode, FeedArticle, article_url, web_url

from .fetch import FeedError

LANGUAGE = re.compile(r"[a-z]{2,8}(?:-[a-z0-9]{1,8}){0,3}", re.ASCII)
MAX_ENTRIES = 1000


def text_only(value) -> str:
    return " ".join(unescape(nh3.clean(str(value or ""), tags=set())).replace("\x00", "").split())


def link_for(entry, base):
    for raw in (entry.get("feedburner_origlink"), entry.get("link")):
        if raw and str(raw).strip():
            try:
                return article_url(urljoin(base, raw.strip()))
            except ValueError:
                continue
    raise ValueError("No publication URL")


def image_for(entry, base):
    for media in entry.get("media_thumbnail", []) + entry.get("media_content", []) + entry.get("enclosures", []):
        media_type = str(media.get("type", ""))
        if media_type and not media_type.startswith("image/"):
            continue
        if media.get("medium") and media["medium"] != "image":
            continue
        raw = media.get("url") or media.get("href")
        if raw:
            try:
                return web_url(urljoin(base, raw.strip()))
            except ValueError:
                continue
    return None


def publication_date(entry):
    for field in ("published_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime.fromtimestamp(timegm(parsed), timezone.utc)
            except (ValueError, OverflowError, OSError):
                continue
    return None


def parse_feed(body, base, source):
    try:
        root = fromstring(body, forbid_dtd=True)
    except (ParseError, DefusedXmlException, LookupError):
        raise FeedError("invalid_feed_xml") from None
    if root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"}:
        raise FeedError("unsupported_feed_format")
    parsed = feedparser.parse(body, response_headers={"content-location": base})
    if parsed.version not in {"rss20", "atom10"}:
        raise FeedError("unsupported_feed_format")
    if len(parsed.entries) > MAX_ENTRIES:
        raise FeedError("too_many_feed_entries")

    entries = []
    for entry in parsed.entries:
        try:
            entries.append(normalize(entry, parsed.feed.get("language"), base, source))
        except (ValueError, ValidationError):
            continue
    if parsed.entries and not entries:
        raise FeedError("no_valid_feed_entries")
    return entries, len(parsed.entries) - len(entries)


def normalize(entry, feed_language, base, source):
    original = link_for(entry, base)
    title = text_only(entry.get("title"))[:500]
    full = next(
        (part.get("value") for part in entry.get("content", [])
         if part.get("type") in {"text/html", "application/xhtml+xml", "text/plain"} and part.get("value")),
        None,
    )
    summary = text_only(entry.get("summary"))
    if full and summary == text_only(full):
        summary = ""
    language = str(entry.get("language") or feed_language or source.language).lower().replace("_", "-")
    if not LANGUAGE.fullmatch(language):
        language = source.language
    guid = str(entry.get("id") or "").replace("\x00", "").strip()
    return FeedArticle(
        title=title, original_url=original, external_guid=guid if 1 <= len(guid) <= 1024 else None,
        summary=summary[:1200] or None,
        content=full if source.content_policy == ContentMode.FULL and full and len(full) <= 100_000 else None,
        author=text_only(entry.get("author"))[:160] or None,
        language=language, published_at=publication_date(entry),
        image_url=image_for(entry, base) if source.allow_images else None,
        tags=[value for tag in entry.get("tags", [])[:30] if (value := text_only(tag.get("term"))[:160])],
    )
