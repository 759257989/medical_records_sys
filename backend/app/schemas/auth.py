# app/schemas/auth.py
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    # from_attributes 让它能直接从 ORM 对象（User 实例）转换
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
    first_name: str
    last_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut