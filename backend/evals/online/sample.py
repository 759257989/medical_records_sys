#
# 从 Langfuse 拉最近的生产生成记录，采样成 Phase 2 套件能直接吃的 case 格式。
# 注意：trace 里的内容已被 Phase 7 脱敏(<PHI>)，所以在线评估跑在去标识数据上(合规)。
from __future__ import annotations

import random

from dotenv import load_dotenv
load_dotenv()

from langfuse import get_client   # noqa: E402

_client = get_client()


def _extract(trace_id: str) -> dict | None:
    """从一条 trace 取出 (转录, 笔记, 成本, 延迟)，拼成统一 case。"""
    full = _client.api.trace.get(trace_id)

    # 转录：root trace 的 input(可能是 {'transcript': ...} 或字符串)
    inp = full.input or {}
    transcript = inp.get("transcript", "") if isinstance(inp, dict) else str(inp)

    # 笔记 + 成本/延迟：从 soap_generation 子节点取
    note, cost, latency = "", 0.0, getattr(full, "latency", 0.0) or 0.0
    for o in (full.observations or []):
        if o.name == "soap_generation":
            note = o.output if isinstance(o.output, str) else (o.output or "")
            cost = getattr(o, "calculated_total_cost", None) or 0.0
    if not note:
        return None                                # 没拿到笔记(异常 trace) → 跳过

    # 推断 label：模型若判信息不足，笔记会以 ###INSUFFICIENT### 开头
    label = "insufficient" if note.strip().startswith("###INSUFFICIENT###") else "valid"
    return {"id": trace_id, "label": label, "transcript": transcript,
            "generated": note, "cost": cost, "latency": latency}


def sample_recent(n: int = 20, pool: int = 200) -> list[dict]:
    """拉最近 pool 条 generate_soap trace，随机采样 n 条并补齐明细。"""
    traces = _client.api.trace.list(name="generate_soap", limit=pool)
    ids = [t.id for t in traces.data]
    random.shuffle(ids)
    cases = []
    for tid in ids:
        if len(cases) >= n:
            break
        c = _extract(tid)
        if c:
            cases.append(c)
    return cases