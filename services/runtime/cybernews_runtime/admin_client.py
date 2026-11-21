import os
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from .contracts import AccountIdentity
from .logs import request_id
from .security import AccountStatus, AdminHeader, Bearer, Role, token_value


def service_url(name: str, default: str) -> str:
    value = os.getenv(name, default)
    address = urlsplit(value)
    if (address.scheme not in {"http", "https"} or not address.hostname or
            address.username is not None or address.password is not None or
            address.path not in {"", "/"} or address.query or address.fragment):
        raise ValueError(f"Invalid {name}")
    return value


class AdminClient:
    def __init__(self, url: str, key: str):
        self.client = httpx.Client(
            base_url=url, timeout=3.0, trust_env=False, headers={"X-Internal-Key": key},
        )

    def close(self):
        self.client.close()

    def require_super_admin(self, token: str, admin_session: str | None) -> AccountIdentity:
        headers = {"Authorization": f"Bearer {token}", "X-Request-ID": request_id.get() or ""}
        if admin_session is not None and len(admin_session) == 43 and admin_session.isascii():
            headers["X-Admin-Session"] = admin_session
        try:
            reply = self.client.get(
                "/internal/v1/principal", params={"require_admin": "true"}, headers=headers,
            )
            if reply.status_code == 401 and reply.headers.get("WWW-Authenticate"):
                raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
            if reply.status_code == 403:
                raise HTTPException(403)
            if reply.status_code == 200:
                user = AccountIdentity.model_validate_json(reply.content)
                if user.role != Role.SUPER_ADMIN or user.status != AccountStatus.ACTIVE:
                    raise HTTPException(403)
                return user
        except (httpx.RequestError, ValidationError):
            pass
        raise HTTPException(503)


def super_admin(request: Request, credentials: Bearer, session: AdminHeader) -> AccountIdentity:
    return request.app.state.admin_client.require_super_admin(token_value(credentials), session)


SuperAdmin = Annotated[AccountIdentity, Depends(super_admin)]
