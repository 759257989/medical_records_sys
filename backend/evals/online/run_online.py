# backend/evals/online/run_online.py
#
# 用法：python -m evals.online.run_online
# 采样生产流量 → 复用 Phase 2 套件评判 → 写 online_scorecard.json(+ 历史)
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from evals.harness import faithfulness, structured_output, task_success
from evals.harness.config import RESULTS_DIR
from evals.online.sample import sample_recent

SAMPLE_N = 20      # 每次评判多少条采样(裁判要花钱，别太多)


async def run() -> dict:
    cases = sample_recent(n=SAMPLE_N)
    if not cases:
        print("没采到生产 trace(Langfuse 里还没有 generate_soap 记录?)")
        return {}

    # 结构校验(免费)+ 两个裁判(贵)；裁判在采样上跑
    so = structured_output.run(cases)
    faith, task = await asyncio.gather(
        faithfulness.run(cases), task_success.run(cases),
    )

    metrics = {
        "structured_output.pass_rate": so["pass_rate"],
        "faithfulness.faithful_rate": faith["faithful_rate"],
        "task_success.pass_rate": task["pass_rate"],
        # 线上特有：真实成本/延迟均值(从采样 trace 来)
        "avg_cost_usd": round(sum(c["cost"] for c in cases) / len(cases), 5),
        "avg_latency_s": round(sum(c["latency"] for c in cases) / len(cases), 3),
        "n_sampled": len(cases),
    }
    record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "metrics": metrics,
              "details": {"structured_output": so, "faithfulness": faith, "task_success": task}}

    # 写当前结果 + 追加到历史(漂移检测要回看)
    (RESULTS_DIR / "online_scorecard.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    hist_path = RESULTS_DIR / "online_history.jsonl"
    with open(hist_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": record["timestamp"], "metrics": metrics}) + "\n")

    print("在线评分:", json.dumps(metrics, indent=2, ensure_ascii=False))
    return record


if __name__ == "__main__":
    asyncio.run(run())