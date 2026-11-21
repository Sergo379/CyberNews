import unicodedata
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, StringConstraints, field_validator, model_validator

from cybernews_runtime.audit import AuditView, Reason
from cybernews_runtime.contracts import AccountIdentity
from cybernews_runtime.security import Role

Nickname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32)]
NewPassword = Annotated[SecretStr, Field(min_length=12, max_length=128)]
Password = Annotated[SecretStr, Field(min_length=1, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountInput(Input):
    @field_validator("nickname", check_fields=False)
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Invalid nickname")
        return value


class Registration(AccountInput):
    email: EmailStr
    nickname: Nickname
    password: NewPassword


class Login(Input):
    email: EmailStr
    password: Password


class ProfileUpdate(AccountInput):
    email: EmailStr | None = None
    nickname: Nickname | None = None

    @model_validator(mode="after")
    def require_fields(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Supply one or more profile fields")
        return self


class ChangePassword(Input):
    current_password: Password
    new_password: NewPassword


class Unlock(Input):
    admin_password: Password


class SetAdminPassword(Input):
    current_password: Password
    admin_password: NewPassword


class RoleChange(Input):
    role: Role
    reason: Reason | None = None


class AccountChange(Input):
    reason: Reason


class Profile(AccountIdentity):
    model_config = ConfigDict(from_attributes=True)

    email: str
    nickname: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class AccessResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AdminSessionView(BaseModel):
    expires_at: datetime


class AdminUnlockResponse(AdminSessionView):
    admin_session: str


class AuthAuditView(AuditView):
    previous_role: Role | None
    new_role: Role | None
