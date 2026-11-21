from html import escape, unescape

import nh3

from cybernews_runtime.news import web_url

TAGS = {
    "a", "blockquote", "br", "code", "em", "figure", "figcaption", "h2", "h3", "h4",
    "hr", "li", "ol", "p", "pre", "strong", "ul",
}


def allowed_url_attribute(tag, name, value):
    if name in {"href", "src"}:
        try:
            return web_url(value)
        except ValueError:
            return None
    return value


def clean_content(value: str, *, allow_images: bool) -> str:
    if "<" not in value:
        value = "".join(f"<p>{escape(line)}</p>" for line in value.splitlines() if line.strip())
    tags = TAGS | {"img"} if allow_images else TAGS
    return nh3.clean(
        value, tags=tags,
        clean_content_tags={"script", "style", "iframe", "svg", "math", "object", "template"},
        attributes={"a": {"href", "title"}, "img": {"src", "alt"}},
        attribute_filter=allowed_url_attribute,
        url_schemes={"https", "http"},
        link_rel="noopener noreferrer nofollow",
    ).strip()


def plain_text(value: str) -> str:
    return unescape(nh3.clean(value, tags=set())).strip()


def external_summary(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(value.split())
    if len(text) > 320:
        prefix = text[:319]
        text = (prefix.rsplit(" ", 1)[0] if " " in prefix else prefix) + "…"
    return text or None
