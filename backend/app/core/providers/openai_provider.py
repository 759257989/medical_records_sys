# backend/app/core/providers/openai_provider.py
#
# OpenAI(GPT-4o) 适配器：实现 ChatProvider。把归一化输入翻译成 Chat Completions 格式，
# 再把返回翻译回归一化 ChatResult。
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.core.providers.base import (
    ChatResult, Message, ToolCall, ToolSpec, Usage,
)
from app.core.providers.pricing import attach_cost

_DEFAULT_MODEL = "gpt-4o"
_EMBED_MODEL = "text-embedding-3-small"


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str):
        # max_retries=0：重试由我们自己的 resilience 层统一负责，避免"双重重试"难以观测。
        self._client = AsyncOpenAI(api_key=api_key, max_retries=0)

    # —— 归一化 messages → OpenAI messages（system 作为第一条）——
    def _to_openai_messages(self, system: str, messages: list[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        out += [{"role": m.role, "content": m.content} for m in messages]
        return out

    def _to_openai_tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        return [
            {"type": "function",
             "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]

    async def complete(
        self, *, system, messages, tools=None, force_tool=None,
        model=None, max_tokens=1024, timeout=30.0,
    ) -> ChatResult:
        model = model or _DEFAULT_MODEL
        tool_choice = (
            {"type": "function", "function": {"name": force_tool}} if force_tool else None
        )
        resp = await self._client.with_options(timeout=timeout).chat.completions.create(
            model=model,
            messages=self._to_openai_messages(system, messages),
            tools=self._to_openai_tools(tools),
            tool_choice=tool_choice,
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name,
                     arguments=json.loads(tc.function.arguments or "{}"))
            for tc in (msg.tool_calls or [])
        ]
        u = resp.usage
        usage = Usage(prompt_tokens=u.prompt_tokens, completion_tokens=u.completion_tokens)
        return ChatResult(
            text=msg.content or "", tool_calls=tool_calls,
            usage=attach_cost(usage, model), model=model, provider=self.name,
        )

    async def stream(
        self, *, system, messages, model=None, max_tokens=2000,
        temperature=0.2, timeout=60.0, usage_sink=None,      # ← 新增 usage_sink
    ):
        model = model or _DEFAULT_MODEL
        stream = await self._client.with_options(timeout=timeout).chat.completions.create(
            model=model,
            messages=self._to_openai_messages(system, messages),
            stream=True, temperature=temperature, max_tokens=max_tokens,
            stream_options={"include_usage": True},          # 最后一帧带 usage
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
            # 末帧 choices 为空、usage 有值 → 回填给调用方
            if getattr(chunk, "usage", None) and usage_sink is not None:
                usage_sink.prompt_tokens = chunk.usage.prompt_tokens
                usage_sink.completion_tokens = chunk.usage.completion_tokens
                usage_sink.model, usage_sink.provider = model, self.name
                attach_cost(usage_sink, model)

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        r = await self._client.embeddings.create(model=_EMBED_MODEL, input=texts)
        return [d.embedding for d in r.data]