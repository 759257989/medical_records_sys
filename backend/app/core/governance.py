# backend/app/core/governance.py
#
# 运行时治理决策：这次生成该用哪个 prompt 版本？走 champion 还是 challenger？
# 全部带"表为空就优雅回退"的兜底，保证治理未配置时系统照常工作。
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.model_routing import ModelRouting
from app.models.prompt_version import PromptVersion


# ── prompt 版本：当前 production 说了算；没有则回退到 settings 默认 ──────────────────
async def resolve_prompt_version(db: AsyncSession) -> str:
    name = await db.scalar(
        select(PromptVersion.name).where(PromptVersion.status == "production")
    )
    return name or settings.prompt_version          # 回退：Phase 3 的静态默认


# ── canary 分流：对稳定 key 做哈希取模，< pct 即落入灰度 ─────────────────────────────
def in_canary(key: str, pct: int) -> bool:
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    bucket = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100
    return bucket < pct                              # 确定性：同一 key 永远同一侧(sticky)


# ── 模型 arm：返回 (主力 provider 名, arm 标签) ─────────────────────────────────────
async def resolve_model_arm(db: AsyncSession, *, task: str = "soap", key: str) -> tuple[str, str]:
    routing = await db.scalar(select(ModelRouting).where(ModelRouting.task == task))
    if routing is None:
        return ("openai", "champion")               # 回退：没配路由就用 openai 主力
    if routing.challenger and in_canary(key, routing.canary_pct):
        return (routing.challenger, "challenger")   # 落入灰度 → 挑战者
    return (routing.champion, "champion")           # 否则 → 冠军