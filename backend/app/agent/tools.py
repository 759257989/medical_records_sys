#
# agent 的工具：包装现有的"查既往史 / 检索 ICD"。节点在图里运行(不在请求里)，
# 所以每个工具自己借一个 SessionLocal 会话，用完即还。
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.api.encounters import query_patient_history   # 复用：查某患者的既往笔记
from app.core.db import SessionLocal
from app.core.llm import embed_text                     # 复用：把文本转向量
from app.models.icd import Icd10Code

TOP_K = 8


async def fetch_history(patient_id: str, exclude_encounter_id: str) -> list[dict]:
    """工具①：取该患者"别的就诊"里的既往笔记(最多 5 条)。"""
    async with SessionLocal() as db:
        return await query_patient_history(
            db, uuid.UUID(patient_id), uuid.UUID(exclude_encounter_id),
        )


async def search_icd(query: str) -> list[dict]:
    """工具②：对一句话做语义检索，返回 top-K 候选 ICD 编码(带相似度分数)。
    复用生产同款查询(embed → 余弦距离排序)。"""
    async with SessionLocal() as db:
        qvec = await embed_text(query)
        if qvec is None:                                # 没向量(mock/没 key) → 关键词兜底
            stmt = (select(Icd10Code.code, Icd10Code.description)
                    .where(Icd10Code.description.ilike(f"%{query}%")).limit(TOP_K))
            rows = (await db.execute(stmt)).all()
            return [{"code": c, "description": d, "score": None} for c, d in rows]
        stmt = (
            select(
                Icd10Code.code, Icd10Code.description,
                (1 - Icd10Code.embedding.cosine_distance(qvec)).label("score"),
            )
            .where(Icd10Code.embedding.isnot(None))
            .order_by(Icd10Code.embedding.cosine_distance(qvec))
            .limit(TOP_K)
        )
        rows = (await db.execute(stmt)).all()
        return [{"code": c, "description": d, "score": round(float(s), 3)} for c, d, s in rows]