# backend/evals/harness/run_evals.py
#
# 评估总入口：python -m evals.harness.run_evals
# 读数据集 → 生成被测笔记 → 跑 4 个套件 → 写 scorecard.json/.md → 打印对照表。
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()                                       # 先加载 .env(API key / DB)

from app.core.config import settings               # noqa: E402 (必须在 load_dotenv 之后)
from app.core.llm import _CHAIN
from evals.harness import (                         # noqa: E402
    faithfulness, rag_eval, structured_output, task_success,
)
from evals.harness.config import (                  # noqa: E402
    ICD_GOLDEN, RESULTS_DIR, SOAP_GOLDEN, THRESHOLDS,
)
from evals.harness.generate import generate_all     # noqa: E402


def _load_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _flatten(scores: dict) -> dict:
    """把嵌套结果拍平成 'suite.metric' → value，方便和 THRESHOLDS 对照。"""
    return {
        "structured_output.pass_rate": scores["structured_output"]["pass_rate"],
        "faithfulness.faithful_rate": scores["faithfulness"]["faithful_rate"],
        "task_success.pass_rate": scores["task_success"]["pass_rate"],
        "rag.recall_at_8": scores["rag"]["recall_at_8"],
        "rag.hit_rate_at_8": scores["rag"]["hit_rate_at_8"],
    }


def _write_markdown(flat: dict, scores: dict, meta: dict) -> str:
    lines = [
        f"# Eval Scorecard — {meta['timestamp']}",
        "",
        f"- prompt_version: `{meta['prompt_version']}`",
        f"- providers: `{meta['providers']}`",
        f"- soap cases: {scores['structured_output']['total']} · icd cases: {scores['rag']['total']}",
        "",
        "| Metric | Score | Threshold | Status |",
        "|---|---|---|---|",
    ]
    for key, val in flat.items():
        thr = THRESHOLDS.get(key)
        status = "—" if thr is None else ("✅ PASS" if val >= thr else "❌ FAIL")
        lines.append(f"| {key} | {val} | {thr if thr is not None else '—'} | {status} |")
    # 附几个有用的辅助数字
    lines += [
        "",
        f"- hallucination_rate: {scores['faithfulness']['hallucination_rate']}",
        f"- task_success avg_scores: {scores['task_success']['avg_scores']}",
        f"- rag MRR: {scores['rag']['mrr']}",
    ]
    return "\n".join(lines)


async def main(check: bool) -> int:
    soap_cases = _load_jsonl(SOAP_GOLDEN)
    icd_cases = _load_jsonl(ICD_GOLDEN)

    # 提示：只有 mock 的话，分数没有意义
    provider_names = [p.name for p in _CHAIN]
    if provider_names == ["mock"]:
        print("⚠️  没有配置真实 API key，只有 mock provider——分数不可信。请在 .env 配 OPENAI_API_KEY。")

    print(f"→ 生成 {len(soap_cases)} 条被测笔记 ...")
    generated = await generate_all(soap_cases)

    print("→ 跑 4 个套件 ...")
    # 三个基于笔记的套件并发跑；rag 独立跑
    so = structured_output.run(generated)                 # 同步(纯解析)
    faith, task, rag = await asyncio.gather(
        faithfulness.run(generated),
        task_success.run(generated),
        rag_eval.run(icd_cases),
    )
    scores = {"structured_output": so, "faithfulness": faith,
              "task_success": task, "rag": rag}

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_version": settings.prompt_version,
        "providers": ",".join(provider_names),
    }
    flat = _flatten(scores)

    # 写 JSON(机器可读，Phase 3 的 CI 会消费它)
    (RESULTS_DIR / "scorecard.json").write_text(
        json.dumps({"meta": meta, "metrics": flat, "details": scores},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    # 写 Markdown(人看 / 贴 PR)
    md = _write_markdown(flat, scores, meta)
    (RESULTS_DIR / "scorecard.md").write_text(md, encoding="utf-8")

    print("\n" + md + "\n")
    print(f"📄 scorecard → {RESULTS_DIR/'scorecard.json'} 和 scorecard.md")

    # --check：任一指标低于阈值就返回非零(给 Phase 3 的 CI 当退出码用)
    if check:
        failed = [k for k, v in flat.items()
                  if k in THRESHOLDS and v < THRESHOLDS[k]]
        if failed:
            print(f"\n❌ 低于阈值: {failed}")
            return 1
        print("\n✅ 全部达标")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="任一指标低于阈值则以非零码退出(CI 用)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.check)))