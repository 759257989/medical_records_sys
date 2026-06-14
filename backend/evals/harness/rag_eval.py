# backend/evals/harness/rag_eval.py
#
# 套件④：ICD 语义检索评估。复用生产的 embed + 向量查询，对照 gold 码算 recall/MRR/hit-rate。
from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.llm import embed_text
from app.models.icd import Icd10Code

TOP_K = 8


def _rank_metrics(predicted: list[str], gold: set[str], k: int = TOP_K) -> dict:
    """对单条查询：predicted 是按相关度排序的 code 列表，gold 是相关 code 集合。"""
    topk = predicted[:k]
    recall = len(set(topk) & gold) / len(gold) if gold else 0.0
    hit = 1.0 if (set(topk) & gold) else 0.0
    mrr = 0.0
    for i, code in enumerate(topk, start=1):       # 找第一个命中的名次
        if code in gold:
            mrr = 1.0 / i
            break
    return {"recall": recall, "hit": hit, "mrr": mrr}


async def _retrieve(db, query: str) -> list[str]:
    """复用生产同款检索：embed query → 按余弦距离取最近 TOP_K 个 ICD code。"""
    qvec = await embed_text(query)
    if qvec is None:                               # 没向量(mock/没 key) → 退化关键词，分数会偏低
        stmt = (select(Icd10Code.code)
                .where(Icd10Code.description.ilike(f"%{query}%"))
                .limit(TOP_K))
    else:
        stmt = (select(Icd10Code.code)
                .where(Icd10Code.embedding.isnot(None))
                .order_by(Icd10Code.embedding.cosine_distance(qvec))
                .limit(TOP_K))
    rows = (await db.execute(stmt)).all()
    return [r[0] for r in rows]


async def run(cases: list[dict]) -> dict:
    per = []
    async with SessionLocal() as db:               # 评估脚本自己借一个会话(脱离 FastAPI 依赖)
        for c in cases:
            predicted = await _retrieve(db, c["query"])
            m = _rank_metrics(predicted, set(c["relevant"]))
            per.append({"id": c["id"], "predicted": predicted, **m})

    n = len(per)
    return {
        "recall_at_8": round(sum(p["recall"] for p in per) / n, 3) if n else 0.0,
        "hit_rate_at_8": round(sum(p["hit"] for p in per) / n, 3) if n else 0.0,
        "mrr": round(sum(p["mrr"] for p in per) / n, 3) if n else 0.0,
        "total": n,
        "misses": [p for p in per if p["hit"] == 0.0],   # 一个都没命中的，重点看
    }