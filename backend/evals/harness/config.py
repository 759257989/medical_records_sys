# backend/evals/harness/config.py
#
# 评估的全局配置：路径、裁判模型、并发、各指标阈值。
# 阈值在 Phase 2 只用于"报告对照"(advisory)；到 Phase 3 才把它接成 CI 的红绿灯。
from __future__ import annotations

from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
EVALS_DIR = Path(__file__).resolve().parent.parent      # backend/evals/
DATASETS_DIR = EVALS_DIR / "datasets"
RESULTS_DIR = EVALS_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SOAP_GOLDEN = DATASETS_DIR / "soap_golden.jsonl"
ICD_GOLDEN = DATASETS_DIR / "icd_retrieval.jsonl"

# ── 裁判模型 ──────────────────────────────────────────────────────────────────
# 用一个"够强"的模型当裁判，最好和被测模型不同/更强，减少"自己判自己"的偏差。
# 这里走 provider 层的 fallback 链(见 judge.py)，模型名通过 force_tool 之外的默认值控制。
JUDGE_MAX_TOKENS = 700

# ── 并发 ──────────────────────────────────────────────────────────────────────
# 同时最多跑几个生成/裁判调用。太高容易撞限流；8 是个稳妥起点。
CONCURRENCY = 8

# ── 各指标阈值(及格线) ──────────────────────────────────────────────────────────
# 这些数字是"目标"，先按经验设，跑出 baseline 后再校准。
THRESHOLDS = {
    "structured_output.pass_rate": 0.90,     # ≥90% 笔记结构合规
    "faithfulness.faithful_rate": 0.90,      # ≥90% 笔记无幻觉
    "task_success.pass_rate": 0.80,          # ≥80% 笔记达到 rubric 及格
    "rag.recall_at_8": 0.80,                 # ICD recall@8 ≥0.80
    "rag.hit_rate_at_8": 0.90,               # ≥90% 查询 top8 内至少命中一个
}