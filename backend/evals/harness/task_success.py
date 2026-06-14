# backend/evals/harness/task_success.py
#
# 套件③：任务成功率。LLM 裁判按 rubric 给三维打分(1-5)，全部≥3 视为"成功"。
from __future__ import annotations

import asyncio

from evals.harness.config import CONCURRENCY
from evals.harness.judge import judge

_DIMS = ["completeness", "clinical_correctness", "format"]

_SCHEMA = {
    "type": "object",
    "properties": {
        "completeness": {"type": "integer", "minimum": 1, "maximum": 5,
                         "description": "Does the note capture all clinically relevant info from the transcript?"},
        "clinical_correctness": {"type": "integer", "minimum": 1, "maximum": 5,
                                 "description": "Are the assessment and plan clinically sound and consistent with the transcript?"},
        "format": {"type": "integer", "minimum": 1, "maximum": 5,
                   "description": "Is it a clean, well-organized SOAP note?"},
        "rationale": {"type": "string", "description": "One sentence justifying the scores."},
    },
    "required": _DIMS + ["rationale"],
}

_SYSTEM = (
    "You are an attending physician grading a resident's SOAP note against the visit "
    "TRANSCRIPT. Score each dimension 1-5 (5=excellent). Be calibrated: a solid, usable "
    "note is a 4. Reserve 5 for excellent and 1-2 for seriously deficient. Call submit_scores."
)

PASS_MIN = 3      # 每一维都 ≥3 才算"任务成功"


async def run(generated_cases: list[dict]) -> dict:
    cases = [c for c in generated_cases if c["label"] == "valid"
             and not c["generated"].startswith("__GENERATION_ERROR__")]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(c: dict) -> dict:
        async with sem:
            user = f"TRANSCRIPT:\n{c['transcript']}\n\nNOTE:\n{c['generated']}"
            # 有人工参考笔记的话，给裁判当锚点(可选)
            if c.get("reference_note"):
                user += f"\n\nREFERENCE NOTE (for comparison):\n{c['reference_note']}"
            s = await judge(system=_SYSTEM, user=user,
                            tool_name="submit_scores", schema=_SCHEMA)
            scores = {d: int(s.get(d, 0)) for d in _DIMS}
            return {
                "id": c["id"],
                "scores": scores,
                "passed": all(scores[d] >= PASS_MIN for d in _DIMS),
                "rationale": s.get("rationale", ""),
            }

    details = await asyncio.gather(*(one(c) for c in cases))
    n = len(details)
    passed = sum(1 for d in details if d["passed"])
    # 每个维度的平均分，方便看"是哪一维拖后腿"
    avg = {d: round(sum(x["scores"][d] for x in details) / n, 2) if n else 0.0
           for d in _DIMS}
    return {
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "avg_scores": avg,
        "total": n,
        "failures": [d for d in details if not d["passed"]],
    }