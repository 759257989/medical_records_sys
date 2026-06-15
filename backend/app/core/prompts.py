# backend/app/core/prompts.py
#
# 极简 prompt 仓库：按版本名从 backend/prompts/ 读取 persona 文本。
# 把"prompt 从哪来"收口在这里，llm.py 不关心是文件还是(将来)数据库。
from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from app.core.config import settings

# backend/app/core/prompts.py → parents[2] = backend/ ；prompts 放在 backend/prompts/
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache(maxsize=8)
def load(version: str | None = None) -> str:
    """读取某个版本的 persona 文本。version 缺省时用 settings.prompt_version。
    用 lru_cache 避免每次生成都读盘(prompt 文件在进程生命周期内不变)。"""
    version = version or settings.prompt_version
    path = PROMPTS_DIR / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt 版本不存在: {path}")
    return path.read_text(encoding="utf-8").strip()


def available() -> list[str]:
    """列出所有已存在的 prompt 版本(给 Phase 4 的治理 UI / 回归矩阵用)。"""
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))