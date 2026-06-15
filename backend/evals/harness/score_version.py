# backend/evals/harness/score_version.py
#
# 用法：python -m evals.harness.score_version soap_v2
# 跑该版本的评分卡 → upsert 到 prompt_versions(status=staged, scorecard=...)
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select                      # noqa: E402
from app.core.db import SessionLocal              # noqa: E402
from app.models.prompt_version import PromptVersion  # noqa: E402
from evals.harness.config import RESULTS_DIR      # noqa: E402


async def _upsert(name: str, scorecard: dict) -> None:
    async with SessionLocal() as db:
        row = await db.scalar(select(PromptVersion).where(PromptVersion.name == name))
        if row is None:
            row = PromptVersion(name=name, status="staged", scorecard=scorecard)
            db.add(row)
        else:
            row.scorecard = scorecard
            if row.status == "draft":              # 已是 production 的不动其状态
                row.status = "staged"
        await db.commit()


def main(name: str) -> int:
    # 子进程里用 PROMPT_VERSION 覆盖默认版本，跑 Phase 2 评分卡(CI 友好：跳过 rag)
    env = {**os.environ, "PROMPT_VERSION": name}
    print(f"→ 为 {name} 跑评分卡 ...")
    r = subprocess.run(
        [sys.executable, "-m", "evals.harness.run_evals", "--no-rag"],
        env=env, cwd=os.getcwd(),
    )
    if r.returncode not in (0, 1):                 # 0=达标 1=低于阈值；都算"跑完了"
        print("评分卡运行失败"); return 2
    metrics = json.loads((RESULTS_DIR / "scorecard.json").read_text())["metrics"]
    asyncio.run(_upsert(name, metrics))
    print(f"✓ {name} 已登记为 staged，scorecard={metrics}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python -m evals.harness.score_version <version>"); sys.exit(2)
    sys.exit(main(sys.argv[1]))