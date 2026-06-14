# backend/evals/harness/judge.py
#
# LLM-as-judge 通用助手：用 force_tool 让裁判模型输出"保证结构化"的 JSON 裁决。
# 这是 faithfulness / task_success 两个套件共用的底座。
from __future__ import annotations

from app.core.llm import _CHAIN                  # 复用 Phase 0 组好的 provider fallback 链
from app.core.providers.base import Message, ToolSpec
from app.core.providers.resilience import complete_with_fallback
from evals.harness.config import JUDGE_MAX_TOKENS


async def judge(*, system: str, user: str, tool_name: str, schema: dict) -> dict:
    """让裁判模型按 schema 输出结构化裁决。
    - system/user：裁判的指令和待评材料
    - tool_name + schema：强制模型"调用"这个工具，从而保证输出形状
    返回：解析好的参数 dict(就是裁决本身)。"""
    tool = ToolSpec(
        name=tool_name,
        description="Return the structured judgement by calling this tool.",
        parameters=schema,
    )
    res = await complete_with_fallback(
        _CHAIN,
        system=system,
        messages=[Message(role="user", content=user)],
        tools=[tool],
        force_tool=tool_name,                     # ← 关键：强制结构化输出
        max_tokens=JUDGE_MAX_TOKENS,
    )
    if not res.tool_calls:                         # 极少数模型不配合，给个清晰报错
        raise RuntimeError(f"judge did not call {tool_name}; text={res.text[:200]!r}")
    return res.tool_calls[0].arguments