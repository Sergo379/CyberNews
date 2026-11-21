from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ContentMode(StrEnum):
    EXTERNAL = "external_source"
    FULL = "full_article"


class ArticleStatus(StrEnum):
    PUBLISHED = "published"
    HIDDEN = "hidden"
    DRAFT = "draft"


CATEGORIES = {
    "vulnerabilities": "Vulnerabilities",
    "malware": "Malware",
    "data-breaches": "Data Breaches",
    "cyberattacks": "Cyberattacks",
    "research": "Research",
    "software-security": "Software Security",
    "other": "Other",
}

TRACKERS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "utm_id",
    "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid",
})


def web_url(value: str) -> str:
    if len(value) > 2048 or any(ch.isspace() or ord(ch) < 32 or ch in {"\\", '"', "<", ">"} for ch in value):
        raise ValueError("Invalid web URL")
    parts = urlsplit(value)
    if (parts.scheme not in {"https", "http"} or not parts.hostname or
            parts.username is not None or parts.password is not None or parts.port == 0):
        raise ValueError("Expected an HTTP(S) URL without credentials")
    # Validate IDNA and the authority before passing it to HTTP clients.
    host = parts.hostname.encode("idna").decode("ascii")
    if "%" in host or not host or parts.netloc.endswith(":"):
        raise ValueError("Invalid web URL host")
    return value


def article_url(value: str) -> str:
    value = web_url(value)
    parts = urlsplit(value)
    if parts.path in {"", "/"} and not parts.query and not parts.fragment:
        raise ValueError("Expected the URL of an individual publication")
    return value


def url_key(value: str) -> str:
    parts = urlsplit(article_url(value))
    default_port = 443 if parts.scheme == "https" else 80
    host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    if parts.port is not None and parts.port != default_port:
        host += f":{parts.port}"
    query = "&".join(
        part for part in parts.query.split("&")
        if unquote_plus(part.partition("=")[0]).casefold() not in TRACKERS
    )
    return urlunsplit((parts.scheme, host, parts.path or "/", query, parts.fragment))


def utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Use a timestamp with a timezone")
    return value.astimezone(timezone.utc)


def no_null(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Invalid text")
    return value


WebUrl = Annotated[str, AfterValidator(web_url)]
ArticleUrl = Annotated[str, AfterValidator(article_url)]
Instant = Annotated[datetime, AfterValidator(utc_datetime)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500), AfterValidator(no_null)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200), AfterValidator(no_null)]
Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000), AfterValidator(no_null)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z]{2,8}(?:-[a-z0-9]{1,8}){0,3}$")]
RightsReference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000), AfterValidator(no_null)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160), AfterValidator(no_null)]
Guid = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024), AfterValidator(no_null)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourcePolicy(Input):
    content_policy: ContentMode = ContentMode.EXTERNAL
    rights_reference: RightsReference | None = None
    allow_images: bool = False

    @model_validator(mode="after")
    def valid_rights(self):
        if (self.content_policy == ContentMode.FULL or self.allow_images) and not self.rights_reference:
            raise ValueError("A documented permission reference is required")
        return self


class VersionedPolicy(SourcePolicy):
    revision: int = Field(ge=1, le=2_147_483_647)


class FeedArticle(Input):
    title: Title
    original_url: ArticleUrl
    external_guid: Guid | None = None
    summary: Summary | None = None
    content: Content | None = None
    author: Label | None = None
    language: Language
    published_at: Instant | None = None
    image_url: WebUrl | None = None
    tags: list[Label] = Field(default_factory=list, max_length=30)


class FeedBatch(Input):
    source_id: UUID
    source_name: Label
    source_url: WebUrl
    policy: VersionedPolicy
    entries: list[FeedArticle] = Field(min_length=1, max_length=20)


class ImportCounts(BaseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicted: int = 0

    def add(self, other: "ImportCounts") -> None:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.conflicted += other.conflicted
