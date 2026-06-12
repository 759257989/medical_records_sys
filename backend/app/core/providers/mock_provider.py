# backend/app/core/providers/mock_provider.py
#
# 兜底 provider：没有任何真 key、或所有真 provider 都失败时启用，返回一段模板，
# 保证"应用永不硬崩"。也方便本地无 key 把整条流水线跑通。
from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.providers.base import ChatResult, Message, Usage

_MOCK_NOTE = (
    "###SUBJECTIVE###\nNot documented.\n"
    "###OBJECTIVE###\nNot documented.\n"
    "###ASSESSMENT###\n- R69: Illness, unspecified\n"
    "###PLAN###\n(Generated in mock mode — no LLM provider available.)\n"
)


class MockProvider:
    name = "mock"

    async def complete(self, *, system, messages, tools=None, force_tool=None,
                       model=None, max_tokens=1024, timeout=30.0) -> ChatResult:
        # 若被要求强制调用工具，就"假装"调用它（参数为空），让上层流程能继续。
        from app.core.providers.base import ToolCall
        tool_calls = [ToolCall(id="mock-call", name=force_tool, arguments={})] if force_tool else []
        return ChatResult(text=_MOCK_NOTE, tool_calls=tool_calls,
                          usage=Usage(), model="mock", provider=self.name)

    async def stream(self, *, system, messages, model=None, max_tokens=2000,
                     temperature=0.2, timeout=60.0) -> AsyncIterator[str]:
        for line in _MOCK_NOTE.splitlines(keepends=True):
            yield line

    async def embed(self, texts):
        return None     # 没向量；icd.py 已有关键词回退