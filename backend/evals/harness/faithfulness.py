# backend/evals/harness/faithfulness.py
#
# 套件②：忠实度/幻觉率。LLM 裁判逐条比对"笔记 vs 转录"，列出无依据的声明。
from __future__ import annotations

import asyncio

from evals.harness.config import CONCURRENCY
from evals.harness.judge import judge

# 裁判返回的结构(schema)：未被支持的声明列表 + 是否整体忠实
_SCHEMA = {
    "type": "object",
    "properties": {
        "unsupported_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clinical claims in the NOTE that are NOT supported by the TRANSCRIPT.",
        },
        "is_faithful": {
            "type": "boolean",
            "description": "True only if the note introduces no clinical facts absent from the transcript.",
        },
    },
    "required": ["unsupported_claims", "is_faithful"],
}

_SYSTEM = (
    "You are a strict clinical-documentation auditor. You are given a visit TRANSCRIPT "
    "and a generated NOTE. Identify every clinical claim in the NOTE that is not grounded "
    "in the TRANSCRIPT (invented diagnoses, meds, vitals, history). General medical "
    "boilerplate and standard formatting are fine. Then call submit_verdict."
)


async def run(generated_cases: list[dict]) -> dict:
    # insufficient 用例没有"笔记内容"可比，跳过——只评应当生成完整笔记的 valid 用例
    cases = [c for c in generated_cases if c["label"] == "valid"
             and not c["generated"].startswith("__GENERATION_ERROR__")]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(c: dict) -> dict:
        async with sem:
            user = f"TRANSCRIPT:\n{c['transcript']}\n\nNOTE:\n{c['generated']}"
            verdict = await judge(system=_SYSTEM, user=user,
                                  tool_name="submit_verdict", schema=_SCHEMA)
            return {
                "id": c["id"],
                "is_faithful": bool(verdict.get("is_faithful")),
                "unsupported_claims": verdict.get("unsupported_claims", []),
            }

    details = await asyncio.gather(*(one(c) for c in cases))
    n = len(details)
    faithful = sum(1 for d in details if d["is_faithful"])
    return {
        "faithful_rate": round(faithful / n, 3) if n else 0.0,
        # 幻觉率 = 1 - 忠实率，简历里两个数都能讲
        "hallucination_rate": round(1 - faithful / n, 3) if n else 0.0,
        "total": n,
        "offenders": [d for d in details if not d["is_faithful"]],
    }