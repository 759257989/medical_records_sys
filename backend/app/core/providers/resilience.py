# backend/app/core/providers/resilience.py
#
# 弹性层：把"调用一个 provider"升级为"带重试地调用 + 失败就换下一个 provider"。
#   - complete：可安全重试 + 跨 provider fallback
#   - stream  ：只在"首 token 之前"做跨 provider fallback（见手册 §3 (B)）
import asyncio
import logging
from collections.abc import AsyncIterator

import anthropic
import openai
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from app.core.providers.base import ChatProvider, ChatResult, Message, ToolSpec

log = logging.getLogger("llm.resilience")

# 哪些异常算"瞬时、值得重试"：超时、限流、连接、5xx。
RETRYABLE = (
    asyncio.TimeoutError,
    openai.RateLimitError, openai.APITimeoutError,
    openai.APIConnectionError, openai.InternalServerError,
    anthropic.RateLimitError, anthropic.APITimeoutError,
    anthropic.APIConnectionError, anthropic.InternalServerError,
)

# 单个 provider 上的重试策略：最多 3 次，指数退避 0.5s→1s→2s（带抖动上限）。
_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    retry=retry_if_exception_type(RETRYABLE),
)


async def complete_with_fallback(
    providers: list[ChatProvider], **kwargs
) -> ChatResult:
    """按顺序尝试每个 provider；单个 provider 内部带重试；全失败才上抛最后一个异常。"""
    last_exc: Exception | None = None
    for p in providers:
        try:
            @_retry
            async def _call():
                return await p.complete(**kwargs)   # noqa: B023 (闭包捕获 p 是有意的)
            result = await _call()
            if p is not providers[0]:
                log.warning("complete fell back to provider=%s", p.name)
            return result
        except Exception as e:               # noqa: BLE001  上一个挂了就试下一个
            last_exc = e
            log.warning("provider=%s complete failed: %s", p.name, e)
            continue
    raise last_exc  # type: ignore[misc]


async def stream_with_fallback(
    providers: list[ChatProvider], **kwargs
) -> AsyncIterator[str]:
    """
    流式 fallback：只在"首 token 之前"换 provider。
    一旦吐出第一个 token，就锁定该 provider；中途异常直接上抛（SSE 层包成 error 事件）。
    """
    last_exc: Exception | None = None
    timeout = kwargs.get("timeout", 60.0)
    for p in providers:
        agen = p.stream(**kwargs)
        try:
            # 关键：给"首 token"单独设超时——provider 卡在建流也能及时回退。
            first = await asyncio.wait_for(agen.__anext__(), timeout=timeout)
        except StopAsyncIteration:
            return                            # 空流：正常结束
        except Exception as e:                # noqa: BLE001  首 token 前失败 → 换下一个
            last_exc = e
            log.warning("provider=%s stream failed before first token: %s", p.name, e)
            await agen.aclose()
            continue

        if p is not providers[0]:
            log.warning("stream fell back to provider=%s", p.name)
        yield first                           # 已锁定该 provider
        async for delta in agen:              # 中途失败会自然上抛，不再回退
            yield delta
        return
    raise last_exc  # type: ignore[misc]