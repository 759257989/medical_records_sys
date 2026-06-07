# app/schemas/admin.py
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


# ── Provider（医生账号）─────────────────────────────────────────────
class ProviderCreate(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # 可直接吃 ORM User 对象
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    created_at: datetime
    # 注意：绝不包含 password_hash


class ActiveUpdate(BaseModel):
    is_active: bool


# ── Template（笔记模板）─────────────────────────────────────────────
class TemplateCreate(BaseModel):
    name: str
    encounter_type: str | None = None
    system_prompt: str
    is_active: bool = True


class TemplateUpdate(BaseModel):
    # 都可选：只传想改的字段（PATCH 语义）
    name: str | None = None
    encounter_type: str | None = None
    system_prompt: str | None = None
    is_active: bool | None = None


class TemplateFull(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    encounter_type: str | None
    system_prompt: str          # admin 要能看到/编辑完整 prompt（provider 下拉只给名字）
    is_active: bool
    created_at: datetime
    updated_at: datetime