# backend/evals/online/drift.py
#
# 对比在线指标 vs 离线基线 / 上一窗口，超阈值则告警。透明、可解释。
from __future__ import annotations

import json
from evals.harness.config import RESULTS_DIR

# 各指标的"可容忍变化";质量类(越大越好)看跌幅，成本/延迟(越小越好)看涨幅
DRIFT_RULES = {
    "faithfulness.faithful_rate": ("drop", 0.05),     # 忠实率跌超 5pp → 告警
    "task_success.pass_rate":     ("drop", 0.05),
    "structured_output.pass_rate":("drop", 0.05),
    "avg_cost_usd":               ("rise", 0.5),       # 成本涨超 50% → 告警
    "avg_latency_s":              ("rise", 0.5),
}


def _load(path):
    try:
        return json.loads((RESULTS_DIR / path).read_text())
    except FileNotFoundError:
        return None


def check() -> list[str]:
    online = _load("online_scorecard.json")
    if not online:
        print("没有在线评分，先跑 run_online"); return []
    cur = online["metrics"]

    # 基线1：离线 scorecard(质量类指标)；基线2：上一窗口(全部指标)
    offline = _load("scorecard.json")
    base_offline = offline["metrics"] if offline else {}
    base_prev = _prev_window()

    alerts = []
    for metric, (direction, tol) in DRIFT_RULES.items():
        c = cur.get(metric)
        if c is None:
            continue
        for label, base in (("offline", base_offline), ("prev", base_prev)):
            b = base.get(metric)
            if b is None:
                continue
            if direction == "drop" and c < b - tol:
                alerts.append(f" {metric} 较 {label} 下跌：{b:.3f} → {c:.3f}")
            if direction == "rise" and b > 0 and c > b * (1 + tol):
                alerts.append(f" {metric} 较 {label} 上涨：{b:.3f} → {c:.3f}")
    return alerts


def _prev_window() -> dict:
    """取上一条(非最新)在线历史，作为环比基线。"""
    try:
        lines = (RESULTS_DIR / "online_history.jsonl").read_text().strip().splitlines()
    except FileNotFoundError:
        return {}
    return json.loads(lines[-2])["metrics"] if len(lines) >= 2 else {}


if __name__ == "__main__":
    for a in check() or ["无漂移"]:
        print(a)