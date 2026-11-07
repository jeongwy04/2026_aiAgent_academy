from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import Input


class Credentials(Input):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

    @field_validator("password", mode="before")
    @classmethod
    def preserve_password(cls, value):
        # Passwords are opaque: surrounding spaces are part of the secret.
        return value

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
