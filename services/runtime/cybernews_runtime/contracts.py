from uuid import UUID

from pydantic import BaseModel

from .security import AccountStatus, Role


class AccountIdentity(BaseModel):
    id: UUID
    role: Role
    status: AccountStatus
