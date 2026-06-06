# app/models/template.py
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 主键，UUID v4 随机生成
    name: Mapped[str] = mapped_column(String(150), nullable=False)                                    # 模板名称，最长 150 字符
    encounter_type: Mapped[str | None] = mapped_column(String(100))                                   # 就诊类型（如门诊/急诊），可为空
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)                                  # 发给 LLM 的系统提示词，决定生成病历的风格与格式
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")    # False 时对用户隐藏，但数据保留
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false") # 软删除标记，True 表示已删除
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))                         # 创建者的用户 ID，系统预置模板可为空
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now()) # 创建时间，由数据库自动填入
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())  # 最后修改时间，每次 UPDATE 自动刷新