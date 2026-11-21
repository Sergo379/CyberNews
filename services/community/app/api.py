from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from cybernews_runtime.audit import Limit, Offset
from cybernews_runtime.security import Db, utc_now
from cybernews_runtime.service_client import Articles, CurrentUser, OptionalUser

from .models import ArticleReaction, Bookmark, Comment, CommentReaction
from .rate_limit import count_attempt
from .reactions import set_reaction, tallies, tally
from .schemas import (
    ArticleIds, ArticleStats, BookmarkView, CommentInput, CommentPage, CommentView,
    ReactionInput, ReactionView, SavedArticle,
)

router = APIRouter(tags=["community"])


def comment_view(comment, reaction):
    return CommentView(
        id=comment.id, article_id=comment.article_id, author_id=comment.author_id, nickname=comment.nickname,
        body=comment.body, created_at=comment.created_at, updated_at=comment.updated_at,
        edited=comment.edited_at is not None, edited_at=comment.edited_at, **reaction.model_dump(),
    )


def published_comment(db, articles, comment_id, *, lock=False):
    comment = db.get(Comment, comment_id)
    if comment is None or comment.status != "published":
        raise HTTPException(404)
    articles.published(comment.article_id)
    if lock:
        comment = db.get(Comment, comment_id, with_for_update=True, populate_existing=True)
        if comment.status != "published":
            raise HTTPException(404)
    return comment


def own_comment(db, comment_id, author_id, *, lock=False):
    comment = db.get(Comment, comment_id, with_for_update=lock, populate_existing=lock)
    if comment is None:
        raise HTTPException(404)
    if comment.author_id != author_id:
        raise HTTPException(403)
    return comment


@router.get("/articles/{article_id}/comments", response_model=CommentPage)
def list_comments(
    article_id: UUID, db: Db, articles: Articles, viewer: OptionalUser,
    limit: Limit = 20, offset: Offset = 0, sort: Literal["oldest", "newest"] = "oldest",
):
    articles.published(article_id)
    filters = (Comment.article_id == article_id, Comment.status == "published")
    sort_order = (Comment.created_at.asc(), Comment.id.asc()) if sort == "oldest" else (
        Comment.created_at.desc(), Comment.id.desc(),
    )
    total = db.scalar(select(func.count()).select_from(Comment).where(*filters))
    rows = list(db.scalars(select(Comment).where(*filters).order_by(*sort_order).limit(limit).offset(offset)))
    stats = tallies(db, CommentReaction, [row.id for row in rows], viewer.id if viewer else None)
    return CommentPage(items=[comment_view(row, stats.get(row.id, ReactionView())) for row in rows],
                       total=total, limit=limit, offset=offset)


@router.post("/articles/{article_id}/comments", response_model=CommentView, status_code=201)
def create_comment(article_id: UUID, data: CommentInput, request: Request, db: Db,
                   articles: Articles, author: CurrentUser):
    count_attempt(request, author.id, "comments")
    articles.published(article_id)
    request.app.state.comment_access.require_permission(author.id)
    comment = Comment(article_id=article_id, author_id=author.id, nickname=author.nickname, body=data.body)
    db.add(comment)
    db.commit()
    return comment_view(comment, ReactionView())


@router.get("/comments/{comment_id}", response_model=CommentView)
def get_comment(comment_id: UUID, db: Db, articles: Articles, viewer: OptionalUser):
    comment = published_comment(db, articles, comment_id)
    return comment_view(comment, tally(db, CommentReaction, comment.id, viewer.id if viewer else None))


@router.patch("/comments/{comment_id}", response_model=CommentView)
def edit_comment(comment_id: UUID, data: CommentInput, request: Request, db: Db,
                 articles: Articles, author: CurrentUser):
    count_attempt(request, author.id, "edits")
    comment = own_comment(db, comment_id, author.id)
    if comment.status != "published":
        raise HTTPException(409)
    articles.published(comment.article_id)
    request.app.state.comment_access.require_permission(author.id)
    comment = own_comment(db, comment_id, author.id, lock=True)
    if comment.status != "published":
        raise HTTPException(409)
    comment.body = data.body
    comment.edited_at = comment.updated_at = utc_now()
    stats = tally(db, CommentReaction, comment.id, author.id)
    db.commit()
    return comment_view(comment, stats)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: UUID, db: Db, author: CurrentUser):
    comment = own_comment(db, comment_id, author.id, lock=True)
    if comment.status != "deleted":
        comment.status = "deleted"
        comment.removed_at = comment.updated_at = utc_now()
        db.commit()


@router.get("/articles/{article_id}/reactions", response_model=ReactionView)
def article_reactions(article_id: UUID, db: Db, articles: Articles, viewer: OptionalUser):
    articles.published(article_id)
    return tally(db, ArticleReaction, article_id, viewer.id if viewer else None)


def update_reaction(db, model, target_id, user_id, reaction):
    if reaction is None:
        db.execute(delete(model).where(model.target_id == target_id, model.user_id == user_id))
    else:
        set_reaction(db, model, target_id, user_id, reaction)
    result = tally(db, model, target_id, user_id)
    db.commit()
    return result


@router.put("/articles/{article_id}/reaction", response_model=ReactionView)
def put_article_reaction(article_id: UUID, data: ReactionInput, request: Request, db: Db,
                         articles: Articles, actor: CurrentUser):
    count_attempt(request, actor.id, "reactions")
    articles.published(article_id)
    return update_reaction(db, ArticleReaction, article_id, actor.id, data.reaction)


@router.delete("/articles/{article_id}/reaction", response_model=ReactionView)
def delete_article_reaction(article_id: UUID, request: Request, db: Db, articles: Articles, actor: CurrentUser):
    count_attempt(request, actor.id, "reactions")
    articles.published(article_id)
    return update_reaction(db, ArticleReaction, article_id, actor.id, None)


@router.get("/comments/{comment_id}/reactions", response_model=ReactionView)
def comment_reactions(comment_id: UUID, db: Db, articles: Articles, viewer: OptionalUser):
    published_comment(db, articles, comment_id)
    return tally(db, CommentReaction, comment_id, viewer.id if viewer else None)


@router.put("/comments/{comment_id}/reaction", response_model=ReactionView)
def put_comment_reaction(comment_id: UUID, data: ReactionInput, request: Request, db: Db,
                         articles: Articles, actor: CurrentUser):
    count_attempt(request, actor.id, "reactions")
    published_comment(db, articles, comment_id, lock=True)
    return update_reaction(db, CommentReaction, comment_id, actor.id, data.reaction)


@router.delete("/comments/{comment_id}/reaction", response_model=ReactionView)
def delete_comment_reaction(comment_id: UUID, request: Request, db: Db, articles: Articles, actor: CurrentUser):
    count_attempt(request, actor.id, "reactions")
    published_comment(db, articles, comment_id, lock=True)
    return update_reaction(db, CommentReaction, comment_id, actor.id, None)


@router.get("/bookmarks", response_model=list[SavedArticle])
def bookmarks(db: Db, articles: Articles, actor: CurrentUser, limit: Limit = 20, offset: Offset = 0):
    rows = list(db.scalars(select(Bookmark).where(Bookmark.user_id == actor.id).order_by(
        Bookmark.created_at.desc(), Bookmark.article_id.desc(),
    ).limit(limit).offset(offset)))
    available = articles.available([row.article_id for row in rows])
    return [SavedArticle(
        article_id=row.article_id, created_at=row.created_at, available=row.article_id in available,
        article=available.get(row.article_id),
    ) for row in rows]


@router.get("/articles/{article_id}/bookmark", response_model=BookmarkView)
def get_bookmark(article_id: UUID, db: Db, articles: Articles, actor: CurrentUser):
    articles.published(article_id)
    row = db.get(Bookmark, (actor.id, article_id))
    return BookmarkView(article_id=article_id, bookmarked=row is not None, created_at=row.created_at if row else None)


@router.put("/articles/{article_id}/bookmark", response_model=BookmarkView)
def put_bookmark(article_id: UUID, request: Request, db: Db, articles: Articles, actor: CurrentUser):
    count_attempt(request, actor.id, "bookmarks")
    articles.published(article_id)
    db.execute(insert(Bookmark).values(user_id=actor.id, article_id=article_id).on_conflict_do_nothing())
    row = db.get(Bookmark, (actor.id, article_id))
    result = BookmarkView(article_id=article_id, bookmarked=True, created_at=row.created_at)
    db.commit()
    return result


@router.delete("/articles/{article_id}/bookmark", status_code=204)
def delete_bookmark(article_id: UUID, request: Request, db: Db, actor: CurrentUser):
    count_attempt(request, actor.id, "bookmarks")
    db.execute(delete(Bookmark).where(Bookmark.user_id == actor.id, Bookmark.article_id == article_id))
    db.commit()


def stats_for(db, article_ids, viewer):
    user_id = viewer.id if viewer else None
    counts = dict(db.execute(select(Comment.article_id, func.count()).where(
        Comment.status == "published", Comment.article_id.in_(article_ids),
    ).group_by(Comment.article_id)).all())
    reactions = tallies(db, ArticleReaction, article_ids, user_id)
    saved = set()
    if viewer:
        saved = set(db.scalars(select(Bookmark.article_id).where(
            Bookmark.user_id == user_id, Bookmark.article_id.in_(article_ids),
        )))
    return [ArticleStats(
        article_id=article_id, comments=counts.get(article_id, 0),
        bookmarked=article_id in saved if viewer else None,
        **reactions.get(article_id, ReactionView()).model_dump(),
    ) for article_id in article_ids]


@router.get("/articles/{article_id}/stats", response_model=ArticleStats)
def article_stats(article_id: UUID, db: Db, articles: Articles, viewer: OptionalUser):
    articles.published(article_id)
    return stats_for(db, [article_id], viewer)[0]


@router.post("/articles/stats", response_model=list[ArticleStats])
def batch_article_stats(data: ArticleIds, db: Db, articles: Articles, viewer: OptionalUser):
    available = articles.available(data.ids)
    return stats_for(db, [article_id for article_id in dict.fromkeys(data.ids) if article_id in available], viewer)
