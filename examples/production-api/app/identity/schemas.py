from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserRead(BaseModel):
    id: UUID
    email: EmailStr


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
