# backend/tests/test_resilience.py
import asyncio

import pytest

from app.core.providers.base import ChatResult, Message, Usage
from app.core.providers.mock_provider import MockProvider
from app.core.providers.resilience import complete_with_fallback, stream_with_fallback


class AlwaysTimeout:
    """模拟一个总是超时的 provider（应触发重试，最终被跳过）。"""
    name = "flaky"
    calls = 0

    async def complete(self, **kwargs):
        AlwaysTimeout.calls += 1
        raise asyncio.TimeoutError("simulated timeout")

    async def stream(self, **kwargs):
        raise asyncio.TimeoutError("simulated timeout")
        yield  # pragma: no cover  让它成为 async generator

    async def embed(self, texts):
        return None


@pytest.mark.asyncio
async def test_complete_falls_back_after_retries():
    flaky = AlwaysTimeout()
    AlwaysTimeout.calls = 0
    chain = [flaky, MockProvider()]
    r = await complete_with_fallback(chain, system="s", messages=[Message("user", "hi")])
    assert r.provider == "mock"             # 退到了 mock
    assert AlwaysTimeout.calls == 3         # 在 flaky 上重试满 3 次才放弃


@pytest.mark.asyncio
async def test_stream_falls_back_before_first_token():
    chain = [AlwaysTimeout(), MockProvider()]
    chunks = [c async for c in stream_with_fallback(
        chain, system="s", messages=[Message("user", "hi")], timeout=2.0)]
    assert "".join(chunks).startswith("###SUBJECTIVE###")   # mock 接管，正常出全文