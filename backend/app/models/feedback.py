# backend/app/models/feedback.py
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class NoteFeedback(Base):
    __tablename__ = "note_feedback"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))   # 关联 Langfuse trace，便于回看
    rating: Mapped[int] = mapped_column(Integer, nullable=False)   # +1 赞 / 0 中性 / -1 踩
    signal: Mapped[str | None] = mapped_column(String(20))        # accept / edit / reject(隐式)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())