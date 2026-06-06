# app/models/patient.py
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 注意：按 (lower(first), lower(last), dob) 去重的“自然键”唯一索引在迁移里建（函数索引）