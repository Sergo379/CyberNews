from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import text, update

from cybernews_runtime.news import ArticleStatus, ContentMode, FeedBatch, ImportCounts, VersionedPolicy, url_key
from cybernews_runtime.security import utc_now

from .classification import classify
from .content import clean_content, external_summary, plain_text
from .models import Article, ArticleGuidKey, ArticleUrlKey, SourcePolicyRecord
from .outbox import record_first_publication


def catalog_lock(db):
    db.execute(text("SELECT pg_advisory_xact_lock(23062431)"))


def apply_policy(db, source_id, policy: VersionedPolicy):
    row = db.get(SourcePolicyRecord, source_id)
    values = policy.model_dump()
    if row is None:
        db.add(SourcePolicyRecord(source_id=source_id, **values))
        db.flush()
        return
    previous = VersionedPolicy.model_validate(row, from_attributes=True)
    if policy.revision < previous.revision or (policy.revision == previous.revision and policy != previous):
        raise HTTPException(409)
    if policy.revision == previous.revision:
        return

    changes = {}
    if policy.content_policy != ContentMode.FULL or policy.rights_reference != previous.rights_reference:
        changes.update(content=None, content_mode=ContentMode.EXTERNAL)
    elif previous.allow_images and not policy.allow_images:
        # Remove inline images immediately. A fresh import can restore the licensed text.
        changes.update(content=None, content_mode=ContentMode.EXTERNAL)
    if not policy.allow_images or policy.rights_reference != previous.rights_reference:
        changes["image_url"] = None
    if changes:
        db.execute(update(Article).where(Article.source_id == source_id).values(**changes, updated_at=utc_now()))
    for name, value in values.items():
        setattr(row, name, value)


def digest(value):
    return sha256(value.encode()).hexdigest()


def update_entry(db, batch, entry) -> str:
    canonical = url_key(entry.original_url)
    url_digest = digest(canonical)
    guid_digest = digest(entry.external_guid) if entry.external_guid else None
    url_row = db.get(ArticleUrlKey, url_digest)
    guid_row = db.get(ArticleGuidKey, (batch.source_id, guid_digest)) if guid_digest else None
    if ((url_row and url_row.normalized_url != canonical) or
            (guid_row and guid_row.guid != entry.external_guid) or
            (url_row and guid_row and url_row.article_id != guid_row.article_id)):
        return "conflicted"

    key = url_row or guid_row
    article = db.get(Article, key.article_id) if key else None
    if article is None:
        article = Article(
            source_id=batch.source_id, source_name=batch.source_name, source_url=batch.source_url,
            original_url=entry.original_url, external_guid=entry.external_guid, status=ArticleStatus.PUBLISHED,
            **entry_fields(batch, entry),
        )
        db.add(article)
        db.flush()
        record_first_publication(db, article)
        outcome = "created"
    elif article.source_id == batch.source_id:
        fields = entry_fields(batch, entry)
        if article.edited:
            fields = {name: fields[name] for name in ("content", "content_mode")}
        else:
            fields.update(source_name=batch.source_name, source_url=batch.source_url)
            if entry.published_at is None:
                fields.pop("published_at")
            if entry.external_guid is not None:
                fields["external_guid"] = entry.external_guid
            # A GUID identifies the same article after a permalink change. Preserve the original
            # link when only tracking fields changed.
            if not url_row or url_key(article.original_url) != canonical:
                fields["original_url"] = entry.original_url
        changed = {name: value for name, value in fields.items() if getattr(article, name) != value}
        for name, value in changed.items():
            setattr(article, name, value)
        if changed:
            article.updated_at = utc_now()
        outcome = "updated" if changed else "unchanged"
    else:
        outcome = "unchanged"

    if url_row is None:
        db.add(ArticleUrlKey(key=url_digest, normalized_url=canonical, article_id=article.id))
    if guid_digest and guid_row is None:
        db.add(ArticleGuidKey(source_id=batch.source_id, key=guid_digest, guid=entry.external_guid, article_id=article.id))
    return outcome


def entry_fields(batch, entry):
    title = plain_text(entry.title) or entry.title
    summary = external_summary(plain_text(entry.summary)) if entry.summary else None
    full = batch.policy.content_policy == ContentMode.FULL
    content = clean_content(entry.content, allow_images=batch.policy.allow_images) if full and entry.content else None
    content = content if content and plain_text(content) else None
    return {
        "title": title, "summary": summary, "content": content,
        "content_mode": ContentMode.FULL if content else ContentMode.EXTERNAL, "author": entry.author,
        "category": classify(title, summary, entry.tags), "language": entry.language,
        "published_at": entry.published_at, "image_url": entry.image_url if batch.policy.allow_images else None,
    }


def import_batch(db, batch: FeedBatch) -> ImportCounts:
    catalog_lock(db)
    apply_policy(db, batch.source_id, batch.policy)
    counts = ImportCounts()
    for entry in batch.entries:
        outcome = update_entry(db, batch, entry)
        setattr(counts, outcome, getattr(counts, outcome) + 1)
        db.flush()
    db.commit()
    return counts
