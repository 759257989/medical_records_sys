import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class ModelRouting(Base):
    __tablename__ = "model_routing"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, default="soap")
    champion: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")     # 默认主力
    challenger: Mapped[str | None] = mapped_column(String(20))                              # 挑战者(可空)
    canary_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)             # 0~100，多少流量给 challenger
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())