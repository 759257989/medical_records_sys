# app/models/__init__.py
from app.models.base import Base
from app.models.user import User
from app.models.patient import Patient
from app.models.template import Template
from app.models.encounter import Encounter
from app.models.note import NoteVersion, NoteVersionCode
from app.models.icd import Icd10Code
from app.models.audit import AuditLog
from app.models.prompt_version import PromptVersion   # ← 新增
from app.models.model_routing import ModelRouting  

__all__ = [
    "Base", "User", "Patient", "Template", "Encounter",
    "NoteVersion", "NoteVersionCode", "Icd10Code", "AuditLog","PromptVersion", "ModelRouting"
]