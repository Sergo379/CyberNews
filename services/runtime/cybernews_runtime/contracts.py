from uuid import UUID

from pydantic import BaseModel

from .security import AccountStatus, Role


class AccountIdentity(BaseModel):
    id: UUID
    role: Role
    status: AccountStatus


class PrincipalIdentity(AccountIdentity):
    nickname: str


class ArticleReference(BaseModel):
    id: UUID
    title: str


class CommentPermission(BaseModel):
    user_id: UUID
    allowed: bool
