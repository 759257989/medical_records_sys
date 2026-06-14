# backend/app/core/providers/anthropic_provider.py
#
# Anthropic(Claude) 适配器：实现 ChatProvider。
# 关键差异（见手册 §3）：system 独立参数；工具用 input_schema；强制调用 {"type":"tool","name"};
# Opus 4.8 已移除 temperature（传了会 400）→ 这里绝不传 temperature。
from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.core.providers.base import (
    ChatResult, Message, ToolCall, ToolSpec, Usage,
)
from app.core.providers.pricing import attach_cost

# 默认用最强的 Opus 4.8（claude-api 技能的默认）。
# 高并发/成本敏感场景可换 "claude-sonnet-4-6"（$3/$15 vs $5/$25）——这是产品决策，不在本篇默认改。
_DEFAULT_MODEL = "claude-opus-4-8"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        self._client = AsyncAnthropic(api_key=api_key, max_retries=0)  # 重试交给 resilience 层

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict]:
        # Claude 的 messages 只有 user/assistant；system 不在数组里（单独传）。
        return [{"role": m.role, "content": m.content} for m in messages]

    def _to_anthropic_tools(self, tools: list[ToolSpec] | None):
        if not tools:
            return None
        # 注意字段是 input_schema，且没有 OpenAI 那层 "function" 包裹。
        return [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]

    async def complete(
        self, *, system, messages, tools=None, force_tool=None,
        model=None, max_tokens=1024, timeout=30.0,
    ) -> ChatResult:
        model = model or _DEFAULT_MODEL
        tool_choice = {"type": "tool", "name": force_tool} if force_tool else None

        kwargs = dict(
            model=model,
            max_tokens=max_tokens,          # Claude 必填 max_tokens（OpenAI 选填）
            system=system,                  # ← 独立参数，不是消息
            messages=self._to_anthropic_messages(messages),
        )
        if tools:
            kwargs["tools"] = self._to_anthropic_tools(tools)
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        # ⚠️ 故意不传 temperature：Opus 4.8 移除了该参数，传了会 400。

        resp = await self._client.with_options(timeout=timeout).messages.create(**kwargs)

        # 响应是 content blocks 列表：type=="text" 取 .text；type=="tool_use" 取 .id/.name/.input
        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))

        usage = Usage(
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
        )
        return ChatResult(
            text="".join(text_parts), tool_calls=tool_calls,
            usage=attach_cost(usage, model), model=model, provider=self.name,
        )

    async def stream(
        self, *, system, messages, model=None, max_tokens=2000,
        temperature=0.2, timeout=60.0, usage_sink=None,      # ← 新增；temperature 仍忽略
    ):
        model = model or _DEFAULT_MODEL
        async with self._client.with_options(timeout=timeout).messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=self._to_anthropic_messages(messages),
        ) as stream:
            async for text in stream.text_stream:
                yield text
            if usage_sink is not None:
                final = await stream.get_final_message()      # 流结束后拿终态用量
                usage_sink.prompt_tokens = final.usage.input_tokens
                usage_sink.completion_tokens = final.usage.output_tokens
                usage_sink.model, usage_sink.provider = model, self.name
                attach_cost(usage_sink, model)

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        # Anthropic 没有 embeddings 接口——向量永远走 OpenAI（见 §3）。
        return None