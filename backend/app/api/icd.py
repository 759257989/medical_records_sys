# app/api/icd.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.llm import embed_text
from app.models.icd import Icd10Code
from app.models.user import User

router = APIRouter(prefix="/api/icd10", tags=["icd10"])


@router.get("/search")
async def search_icd(
    q: str = Query(..., min_length=1),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = q.strip()
    qvec = await embed_text(query)   # 有 key → 向量；没 key → None

    if qvec is not None:
        # 语义检索：按余弦距离排序，取最近 8 个。score = 1 - 距离（越接近 1 越像）
        stmt = (
            select(
                Icd10Code.code,
                Icd10Code.description,
                (1 - Icd10Code.embedding.cosine_distance(qvec)).label("score"),
            )
            .where(Icd10Code.embedding.isnot(None))
            .order_by(Icd10Code.embedding.cosine_distance(qvec))
            .limit(8)
        )
        rows = (await db.execute(stmt)).all()
        return [{"code": c, "description": d, "score": round(float(s), 3)} for (c, d, s) in rows]

    # 降级：关键词匹配（mock 模式 / 向量未灌）
    stmt = (
        select(Icd10Code.code, Icd10Code.description)
        .where(Icd10Code.description.ilike(f"%{query}%"))
        .order_by(Icd10Code.description)
        .limit(8)
    )
    rows = (await db.execute(stmt)).all()
    return [{"code": c, "description": d, "score": None} for (c, d) in rows]