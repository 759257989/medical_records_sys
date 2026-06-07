# app/api/templates.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.template import Template
from app.models.user import User
from app.schemas.template import TemplateOut

router = APIRouter(prefix="/api/templates", tags=["templates"])

# 给工作区的「模板下拉框」提供数据。
@router.get("", response_model=list[TemplateOut])
async def list_templates(
    _user: User = Depends(get_current_user),   # 登录即可访问
    db: AsyncSession = Depends(get_db),
):
    # 只返回未删除、启用中的模板，供前端下拉选择
    rows = await db.scalars(
        select(Template)
        .where(Template.is_deleted.is_(False), Template.is_active.is_(True))
        .order_by(Template.name)
    )
    return list(rows)