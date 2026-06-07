# app/schemas/template.py
import uuid

from pydantic import BaseModel, ConfigDict


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # 可直接从 ORM 对象转换
    id: uuid.UUID
    name: str
    encounter_type: str | None