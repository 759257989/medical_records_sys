# app/schemas/encounter.py
import uuid
from datetime import date

from pydantic import BaseModel


class EncounterCreate(BaseModel):
    first_name: str
    last_name: str
    dob: date                      # 前端传 "YYYY-MM-DD"，自动解析成 date
    template_id: uuid.UUID | None = None


class GenerateRequest(BaseModel):
    transcript: str