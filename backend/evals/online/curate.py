# backend/evals/online/curate.py
#
# 从最近一次在线评估的失败明细里，挑出"难/失败"case → 候选金标准(待人审)。
# 人审是必须的：不能让自动流程直接污染金标准。
from __future__ import annotations

import json
from evals.harness.config import RESULTS_DIR, DATASETS_DIR

CANDIDATES = DATASETS_DIR / "soap_golden_candidates.jsonl"


def curate() -> int:
    online = json.loads((RESULTS_DIR / "online_scorecard.json").read_text())
    d = online["details"]

    # 收集失败 case 的 id + 原因(结构不合规 / 幻觉 / 任务不达标)
    reasons: dict[str, list[str]] = {}
    for f in d["structured_output"].get("failures", []):
        reasons.setdefault(f["id"], []).append(f"structure: {f['reason']}")
    for o in d["faithfulness"].get("offenders", []):
        reasons.setdefault(o["id"], []).append(f"hallucination: {o['unsupported_claims']}")
    for f in d["task_success"].get("failures", []):
        reasons.setdefault(f["id"], []).append("task_success: below rubric")
    if not reasons:
        print("本轮没有失败 case，飞轮无新增"); return 0

    # 去重:已在候选里的 trace id 不重复写
    seen = set()
    if CANDIDATES.exists():
        seen = {json.loads(l)["id"] for l in CANDIDATES.read_text().splitlines() if l.strip()}

    # 重新采样明细里拿不到转录原文?——失败明细只有 id；这里从在线 details 里没有原文，
    # 所以候选只记 id + 原因 + 待补转录的占位，提示人审时去 Langfuse 按 id 调原文核对。
    added = 0
    with open(CANDIDATES, "a", encoding="utf-8") as out:
        for tid, why in reasons.items():
            if tid in seen:
                continue
            out.write(json.dumps({
                "id": tid, "status": "pending_review", "reasons": why,
                "hint": f"在 Langfuse 按 trace id {tid} 调原始转录/笔记，整理成 soap_golden 条目后并入",
            }, ensure_ascii=False) + "\n")
            added += 1
    print(f"飞轮新增 {added} 条候选 → {CANDIDATES.name}(待人审)")
    return added


if __name__ == "__main__":
    curate()