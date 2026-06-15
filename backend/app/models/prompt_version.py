# backend/app/models/prompt_version.py
#
# prompt 版本的治理记录。正文仍在 prompts/soap_vN.md；这张表只管"治理状态"：
# 它现在处于什么阶段、最近一次评分卡是多少、谁登记的。
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 版本名 == prompts/ 下的文件名(去掉 .md)，如 "soap_v1"；唯一
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # 生命周期：draft(刚登记) → staged(已评分、候选) → production(线上生效)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # 最近一次评分卡(Phase 2 的 metrics)；晋升闸门据此比较
    scorecard: Mapped[dict | None] = mapped_column(JSONB)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())