from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, literal_column, select

from cybernews_runtime.admin_client import SuperAdmin
from cybernews_runtime.audit import AuditView, Limit, Offset, add_event, audit_query
from cybernews_runtime.contracts import ArticleReference
from cybernews_runtime.news import ArticleStatus, ContentMode, FeedBatch, ImportCounts, Instant, VersionedPolicy
from cybernews_runtime.security import Db, require_service_key, utc_now

from .config import article_read_key, import_key
from .content import clean_content, external_summary, plain_text
from .ingestion import apply_policy, catalog_lock, import_batch
from .models import Article, ArticleAudit, Category, SourcePolicyRecord
from .outbox import record_first_publication
from .schemas import ArticlePage, ArticleView, AvailabilityRequest, CategoryId, CategoryView, EditorialUpdate, OriginalCreate, SearchText, SourceView

public = APIRouter(tags=["articles"])
admin = APIRouter(prefix="/admin", tags=["article administration"])
internal = APIRouter(prefix="/internal/v1", include_in_schema=False)


@public.get("/", response_model=ArticlePage)
@public.get("/search", response_model=ArticlePage)
def list_articles(
    db: Db, q: SearchText | None = None, category: CategoryId | None = None, source_id: UUID | None = None,
    published_from: Instant | None = None, published_to: Instant | None = None,
    sort: Literal["newest", "oldest"] = "newest", limit: Limit = 20, offset: Offset = 0,
):
    if published_from and published_to and published_from > published_to:
        raise HTTPException(422)
    filters = [Article.status == ArticleStatus.PUBLISHED]
    if q:
        if "\x00" in q:
            raise HTTPException(422)
        search = func.websearch_to_tsquery(literal_column("'simple'::regconfig"), q)
        filters.append(Article.search_document.bool_op("@@")(search))
    if category:
        filters.append(Article.category == category)
    if source_id:
        filters.append(Article.source_id == source_id)
    if published_from:
        filters.append(Article.published_at >= published_from)
    if published_to:
        filters.append(Article.published_at <= published_to)
    date_order = Article.published_at.desc() if sort == "newest" else Article.published_at.asc()
    order_by = (date_order.nulls_last(), Article.collected_at.desc(), Article.id.desc())
    total = db.scalar(select(func.count()).select_from(Article).where(*filters))
    items = db.scalars(select(Article).where(*filters).order_by(*order_by).limit(limit).offset(offset))
    return {"items": list(items), "total": total, "limit": limit, "offset": offset}


@public.get("/categories", response_model=list[CategoryView])
def categories(db: Db):
    return list(db.scalars(select(Category).order_by(Category.name)))


@public.get("/sources", response_model=list[SourceView])
def sources(db: Db):
    # Keep one public snapshot per source UUID, using its latest published article.
    partition = Article.source_id
    source_rows = select(
        Article.source_id, Article.source_name, Article.source_url,
        func.count().over(partition_by=partition).label("total"),
        func.row_number().over(
            partition_by=partition, order_by=(Article.updated_at.desc(), Article.id.desc()),
        ).label("position"),
    ).where(Article.status == ArticleStatus.PUBLISHED).subquery()
    items = db.execute(select(
        source_rows.c.source_id, source_rows.c.source_name, source_rows.c.source_url, source_rows.c.total,
    ).where(source_rows.c.position == 1).order_by(source_rows.c.source_name))
    return [SourceView(id=identifier, name=name, url=url, count=count) for identifier, name, url, count in items]


@public.get("/{article_id}", response_model=ArticleView)
def get_article(article_id: UUID, db: Db):
    article = db.get(Article, article_id)
    if article is None or article.status != ArticleStatus.PUBLISHED:
        raise HTTPException(404)
    return article


@admin.get("/articles", response_model=list[ArticleView])
def admin_list(_: SuperAdmin, db: Db, status: ArticleStatus | None = None, limit: Limit = 50, offset: Offset = 0):
    query = select(Article).order_by(Article.updated_at.desc(), Article.id.desc()).limit(limit).offset(offset)
    if status is not None:
        query = query.where(Article.status == status)
    return list(db.scalars(query))


def editorial_text(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    if field == "content":
        cleaned = clean_content(value, allow_images=True)
        if not cleaned or not plain_text(cleaned):
            raise HTTPException(422)
        return cleaned
    cleaned = plain_text(value)
    if field == "title" and not cleaned:
        raise HTTPException(422)
    return cleaned or None


@admin.post("/articles", response_model=ArticleView, status_code=201)
def create_article(data: OriginalCreate, actor: SuperAdmin, db: Db):
    fields = data.model_dump()
    for field in ("title", "summary", "content", "author"):
        fields[field] = editorial_text(field, fields[field])
    if data.status == ArticleStatus.PUBLISHED and data.published_at is None:
        fields["published_at"] = utc_now()
    article = Article(**fields, source_name="CyberNews", content_mode=ContentMode.FULL, edited=True)
    db.add(article)
    db.flush()
    record_first_publication(db, article)
    add_event(db, ArticleAudit, actor.id, "article_created", article.id)
    db.commit()
    return article


def mutable_article(db, article_id):
    catalog_lock(db)
    article = db.get(Article, article_id, with_for_update=True)
    if article is None:
        raise HTTPException(404)
    return article


@admin.patch("/articles/{article_id}", response_model=ArticleView)
def edit_article(article_id: UUID, data: EditorialUpdate, actor: SuperAdmin, db: Db):
    article = mutable_article(db, article_id)
    changes = data.model_dump(exclude_unset=True)
    if article.source_id is not None:
        policy = db.get(SourcePolicyRecord, article.source_id)
        if "content" in changes or ("image_url" in changes and changes["image_url"] and not policy.allow_images):
            raise HTTPException(403)
        if changes.get("summary"):
            changes["summary"] = external_summary(editorial_text("summary", changes["summary"]))
    if "status" in changes and article.status == ArticleStatus.HIDDEN:
        raise HTTPException(409)
    for field in {"title", "summary", "content", "author"} & changes.keys():
        changes[field] = editorial_text(field, changes[field])
    for field, value in changes.items():
        setattr(article, field, value)
    if article.source_id is None and article.status == ArticleStatus.PUBLISHED and article.published_at is None:
        article.published_at = utc_now()
    article.edited = True
    article.updated_at = utc_now()
    record_first_publication(db, article)
    add_event(db, ArticleAudit, actor.id, "article_edited", article.id)
    db.commit()
    return article


@admin.post("/articles/{article_id}/hide", response_model=ArticleView)
def hide_article(article_id: UUID, actor: SuperAdmin, db: Db):
    article = mutable_article(db, article_id)
    if article.status == ArticleStatus.HIDDEN:
        raise HTTPException(409)
    article.previous_status = article.status
    article.status = ArticleStatus.HIDDEN
    article.updated_at = utc_now()
    add_event(db, ArticleAudit, actor.id, "article_hidden", article.id)
    db.commit()
    return article


@admin.post("/articles/{article_id}/restore", response_model=ArticleView)
def restore_article(article_id: UUID, actor: SuperAdmin, db: Db):
    article = mutable_article(db, article_id)
    if article.status != ArticleStatus.HIDDEN:
        raise HTTPException(409)
    article.status = article.previous_status
    article.previous_status = None
    article.updated_at = utc_now()
    add_event(db, ArticleAudit, actor.id, "article_restored", article.id)
    db.commit()
    return article


@admin.get("/audit", response_model=list[AuditView])
def audit(_: SuperAdmin, db: Db, limit: Limit = 50, offset: Offset = 0):
    return list(db.scalars(audit_query(ArticleAudit, None, limit, offset)))


def require_importer(request: Request) -> None:
    require_service_key(request, import_key)


def require_reader(request: Request) -> None:
    require_service_key(request, article_read_key)


@internal.get("/articles/{article_id}", response_model=ArticleReference, dependencies=[Depends(require_reader)])
def published_reference(article_id: UUID, db: Db):
    result = db.execute(select(Article.id, Article.title).where(
        Article.id == article_id, Article.status == ArticleStatus.PUBLISHED,
    )).one_or_none()
    if result is None:
        raise HTTPException(404)
    return ArticleReference(id=result.id, title=result.title)


@internal.post("/articles/availability", response_model=list[ArticleReference], dependencies=[Depends(require_reader)])
def article_availability(data: AvailabilityRequest, db: Db):
    rows = db.execute(select(Article.id, Article.title).where(
        Article.id.in_(data.ids), Article.status == ArticleStatus.PUBLISHED,
    ))
    return [ArticleReference(id=row.id, title=row.title) for row in rows]


@internal.post("/import", response_model=ImportCounts, dependencies=[Depends(require_importer)])
def ingest(data: FeedBatch, db: Db):
    return import_batch(db, data)


@internal.put("/sources/{source_id}/policy", status_code=204, dependencies=[Depends(require_importer)])
def update_policy(source_id: UUID, data: VersionedPolicy, db: Db):
    catalog_lock(db)
    apply_policy(db, source_id, data)
    db.commit()
