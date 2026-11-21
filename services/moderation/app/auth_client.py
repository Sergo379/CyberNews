from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from cybernews_runtime.contracts import AccountIdentity
from cybernews_runtime.logs import request_id
from cybernews_runtime.security import AdminHeader, Bearer, Role, token_value

from .config import auth_service_url, internal_key


class AuthClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=auth_service_url, timeout=httpx.Timeout(3.0), trust_env=False,
            headers={"X-Internal-Key": internal_key},
        )

    def close(self):
        self.client.close()

    def ready(self) -> bool:
        try:
            return self.client.get("/ready").status_code == 200
        except httpx.RequestError:
            return False

    def _get(self, path, *, headers=None, params=None, accepted_errors=()):
        try:
            response = self.client.get(
                path, headers={**(headers or {}), "X-Request-ID": request_id.get() or ""}, params=params,
            )
            if response.status_code in accepted_errors:
                headers = {"WWW-Authenticate": "Bearer"} if response.status_code == 401 else None
                raise HTTPException(response.status_code, headers=headers)
            if response.status_code == 200:
                return AccountIdentity.model_validate_json(response.content)
        except (httpx.RequestError, ValidationError):
            pass
        raise HTTPException(503)

    def principal(self, token: str, admin_session: str | None = None, *, require_admin: bool = False):
        headers = {"Authorization": f"Bearer {token}"}
        if admin_session is not None and len(admin_session) == 43 and admin_session.isascii():
            headers["X-Admin-Session"] = admin_session
        return self._get(
            "/internal/v1/principal", headers=headers,
            params={"require_admin": require_admin}, accepted_errors=(401, 403),
        )

    def user(self, user_id: UUID):
        return self._get(f"/internal/v1/users/{user_id}", accepted_errors=(404,))


def auth_client(request: Request) -> AuthClient:
    return request.app.state.auth_client


Auth = Annotated[AuthClient, Depends(auth_client)]


def active_identity(credentials: Bearer, auth: Auth) -> AccountIdentity:
    return auth.principal(token_value(credentials))


def administrator(credentials: Bearer, token: AdminHeader, auth: Auth) -> AccountIdentity:
    return auth.principal(token_value(credentials), token, require_admin=True)


def super_admin(identity: Annotated[AccountIdentity, Depends(administrator)]) -> AccountIdentity:
    if identity.role != Role.SUPER_ADMIN:
        raise HTTPException(403)
    return identity


Active = Annotated[AccountIdentity, Depends(active_identity)]
Administrator = Annotated[AccountIdentity, Depends(administrator)]
SuperAdmin = Annotated[AccountIdentity, Depends(super_admin)]
