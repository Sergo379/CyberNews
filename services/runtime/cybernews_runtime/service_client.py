from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import TypeAdapter, ValidationError

from .contracts import AccountIdentity, ArticleReference, CommentPermission, PrincipalIdentity
from .logs import request_id
from .security import AccountStatus, Bearer, token_value


class ServiceClient:
    def __init__(self, url: str, key: str, *, timeout: float = 3.0):
        self.client = httpx.Client(
            base_url=url, timeout=timeout, trust_env=False, headers={"X-Internal-Key": key},
        )

    def close(self):
        self.client.close()

    def ready(self) -> bool:
        try:
            return self.client.get("/ready").status_code == 200
        except httpx.RequestError:
            return False

    def request(self, method, path, *, payload=None, headers=None, expected_errors=()):
        try:
            response = self.client.request(
                method, path, json=payload,
                headers={"X-Request-ID": request_id.get() or "", **(headers or {})},
            )
        except httpx.RequestError:
            raise HTTPException(503) from None
        if response.status_code in expected_errors:
            raise HTTPException(response.status_code)
        if not response.is_success:
            raise HTTPException(503)
        return response

    def model(self, schema, method, path, **kwargs):
        response = self.request(method, path, **kwargs)
        try:
            return schema.model_validate_json(response.content)
        except ValidationError:
            raise HTTPException(503) from None

    def models(self, schema, method, path, **kwargs):
        response = self.request(method, path, **kwargs)
        try:
            return TypeAdapter(list[schema]).validate_json(response.content)
        except ValidationError:
            raise HTTPException(503) from None


class IdentityClient(ServiceClient):
    def account(self, user_id: UUID) -> AccountIdentity:
        return self.model(AccountIdentity, "GET", f"/internal/v1/users/{user_id}", expected_errors=(404,))

    def principal(self, token: str) -> PrincipalIdentity:
        identity = self.model(
            PrincipalIdentity, "GET", "/internal/v1/principal",
            headers={"Authorization": f"Bearer {token}"}, expected_errors=(401,),
        )
        if identity.status != AccountStatus.ACTIVE:
            raise HTTPException(401)
        return identity


class ArticleReader(ServiceClient):
    def published(self, article_id: UUID) -> ArticleReference:
        return self.model(ArticleReference, "GET", f"/internal/v1/articles/{article_id}", expected_errors=(404,))

    def available(self, article_ids: list[UUID]) -> dict[UUID, ArticleReference]:
        if not article_ids:
            return {}
        items = self.models(
            ArticleReference, "POST", "/internal/v1/articles/availability",
            payload={"ids": [str(item) for item in article_ids]},
        )
        return {item.id: item for item in items}


class CommentAccess(ServiceClient):
    def require_permission(self, user_id: UUID):
        result = self.model(CommentPermission, "GET", f"/internal/v1/comment-permission/{user_id}")
        if result.user_id != user_id:
            raise HTTPException(503)
        if not result.allowed:
            raise HTTPException(403)


def authenticated(request: Request, credentials: Bearer) -> PrincipalIdentity:
    return request.app.state.identity_client.principal(token_value(credentials))


def optional_identity(request: Request, credentials: Bearer) -> PrincipalIdentity | None:
    if credentials is None and "Authorization" not in request.headers:
        return None
    return authenticated(request, credentials)


def article_reader(request: Request) -> ArticleReader:
    return request.app.state.article_reader


CurrentUser = Annotated[PrincipalIdentity, Depends(authenticated)]
OptionalUser = Annotated[PrincipalIdentity | None, Depends(optional_identity)]
Articles = Annotated[ArticleReader, Depends(article_reader)]
