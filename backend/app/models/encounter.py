# app/models/encounter.py
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (
        # 数据库层约束：status 只允许三个合法值，防止业务层写入脏数据
        CheckConstraint("status IN ('draft','generated','finalized')", name="ck_enc_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 主键，UUID v4
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)          # 关联的患者
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)            # 负责本次就诊的医生/提供者
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"))  # 使用的笔记模板；模板被删后置 NULL，不影响历史记录
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    # status 状态流转：draft（录音/录入中）→ generated（AI 已生成草稿）→ finalized（医生签核完成）
    transcript: Mapped[str | None] = mapped_column(Text)    # 音频转录的原始文本，作为 LLM 生成笔记的输入
    working_note: Mapped[dict | None] = mapped_column(JSONB) # 编辑中的 SOAP 草稿，前端 autosave 写入；结构示例：{"S":…,"O":…,"A":…,"P":…}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # 就诊记录创建时间
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())  # 最后修改时间