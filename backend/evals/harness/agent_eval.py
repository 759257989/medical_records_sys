# 端到端跑 agent，统计：工具选择是否符合预期、自我批评回环次数、是否撞 recursion 上限、是否需人审。
# 用法：python -m evals.harness.agent_eval
from __future__ import annotations

import asyncio, uuid
from dotenv import load_dotenv
load_dotenv()

from app.agent import service                      # noqa: E402
from app.agent.checkpointer import ensure_setup    # noqa: E402

# 小数据集：场景 → 期望路径(是否应触发取既往史 / 是否应进人审)
CASES = [
    {"transcript": "Follow-up of type 2 diabetes, A1c 7.2, continue metformin.",
     "has_history": True,  "expect_history_node": True},
    {"transcript": "New patient, acute ankle sprain after fall, RICE and NSAIDs.",
     "has_history": False, "expect_history_node": False},
]


async def run_one(case: dict) -> dict:
    run_id = str(uuid.uuid4())
    initial = {"encounter_id": str(uuid.uuid4()), "provider_id": "eval",
               "patient_id": str(uuid.uuid4()), "transcript": case["transcript"],
               "has_history": case["has_history"]}
    nodes_seen, hit_recursion, needed_approval, done = [], False, False, False
    async for ev in service.start_run(run_id, initial):
        if ev["type"] == "step": nodes_seen.append(ev["node"])
        if ev["type"] == "error": hit_recursion = True
        if ev["type"] == "approval_required": needed_approval = True
        if ev["type"] == "done": done = True
    # 工具选择是否正确：该取史就该看到 retrieve_history 节点
    history_ok = ("retrieve_history" in nodes_seen) == case["expect_history_node"]
    return {"history_ok": history_ok, "revisions": nodes_seen.count("draft") - 1,
            "hit_recursion": hit_recursion, "needed_approval": needed_approval, "done": done}


async def main():
    await ensure_setup()        # 独立脚本不走 FastAPI lifespan，这里自己建一次检查点表（幂等）
    results = [await run_one(c) for c in CASES]
    n = len(results)
    print("工具选择准确率:", sum(r["history_ok"] for r in results) / n)
    print("平均自我批评回环:", sum(max(r["revisions"], 0) for r in results) / n)
    print("撞 recursion 上限比例:", sum(r["hit_recursion"] for r in results) / n, "(应为 0)")
    print("需人审比例:", sum(r["needed_approval"] for r in results) / n)
    print("完成率:", sum(r["done"] or r["needed_approval"] for r in results) / n)

if __name__ == "__main__":
    asyncio.run(main())