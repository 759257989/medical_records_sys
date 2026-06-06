# app/models/icd.py
import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base


class Icd10Code(Base):
    __tablename__ = "icd10_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))