# 租户(诊所)。一行 = 一个客户；带一点"按租户配置"(限流/预算)。
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)   # 如 "clinic-a"
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # 按租户配置(可选)：限流 / 月度成本预算(美元) —— 噪声邻居隔离 + 成本归属
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    monthly_budget_usd: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())