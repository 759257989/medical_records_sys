# 归一化层：定义"与厂商无关"的输入/输出数据结构 + ChatProvider 协议。
# OpenAIProvider 和 AnthropicProvider 都实现这个协议，上层只认这些类型。
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["user", "assistant"]   # 注意：不含 system —— system 单独传（见 base 设计 §3）


@dataclass
class Message:
    """一条对话消息。system 不在这里——它是 complete/stream 的独立参数。"""
    role: Role
    content: str


@dataclass
class ToolSpec:
    """归一化的工具定义。parameters 是标准 JSON Schema（object）。"""
    name: str
    description: str
    parameters: dict[str, Any]   # 例如 {"type":"object","properties":{},"required":[]}


@dataclass
class ToolCall:
    """模型请求调用某工具（已把参数解析成 dict）。"""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    """一次调用的用量与成本。cost_usd 由 pricing.py 按价目表算出。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ChatResult:
    """非流式调用的归一化返回。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""


@runtime_checkable
class ChatProvider(Protocol):
    """每个厂商适配器要实现的接口。上层（resilience/facade）只依赖这个协议。"""
    name: str          # "openai" / "anthropic" / "mock"，记账与日志用

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        force_tool: str | None = None,    # 给名字=强制调用该工具
        model: str | None = None,         # None=用 provider 默认模型
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ChatResult: ...

    async def stream(
        self,
        *,
        system: str,
        messages: list[Message],
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.2,         # 仅 OpenAI 会用；Anthropic 故意忽略（见 §3）
        timeout: float = 60.0,
    ) -> AsyncIterator[str]: ...           # 逐段产出文本增量（纯 str）

    async def embed(self, texts: list[str]) -> list[list[float]] | None: ...