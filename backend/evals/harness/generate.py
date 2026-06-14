# backend/evals/harness/generate.py
#
# 把 soap_golden 里的每条 transcript 跑成一条"被测笔记"。
# 三个基于笔记的套件(结构/忠实/任务成功)共用这一批结果，所以只生成一次。
from __future__ import annotations

import asyncio

from app.core.llm import generate_note
from evals.harness.config import CONCURRENCY


async def generate_all(cases: list[dict]) -> list[dict]:
    """对每个 case 生成笔记，并发受 CONCURRENCY 限制。
    返回 [{**case, "generated": <note text>}]，顺序与输入一致。"""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(case: dict) -> dict:
        async with sem:                          # 限流：同时最多 CONCURRENCY 个在跑
            try:
                note = await generate_note(case["transcript"])
            except Exception as e:               # noqa: BLE001 单条失败不拖垮整批
                note = f"__GENERATION_ERROR__: {e}"
            return {**case, "generated": note}

    # gather 保序：返回顺序与 cases 一致，方便和数据集对齐
    return await asyncio.gather(*(one(c) for c in cases))