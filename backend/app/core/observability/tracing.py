# backend/app/core/observability/tracing.py
#
# LLM 可观测性埋点层。对外暴露：trace()（根，含 .generation()/.span() 子节点工厂）
# 和 span()（给 icd.py 这种独立 span 用）。内部用 Langfuse Python SDK v4。
# 没配 key → 全部安全 no-op。
#
# ⚠️ 关键设计：本模块**全程使用"手动 observation"**（start_observation + 手动 .end()），
#   而**不用** start_as_current_observation / propagate_attributes 去长期占用 OTel 当前上下文。
#   原因：generate_soap_stream 是异步生成器，会在 span 还开着时 `yield` 出去做 SSE 流式。
#   OTel 的当前上下文基于 contextvars，跨 `yield` 挂起/恢复会落到不同的 Context，
#   退出 with 时 detach 那个 token 就会报 “Token was created in a different Context”，
#   在 Starlette/anyio 的 SSE 下会让流卡死。手动 observation 不 attach/detach 当前上下文，
#   父子靠对象显式串联（parent.start_observation(...)），因此跨 yield 完全安全。
from __future__ import annotations

import logging
from contextlib import contextmanager

from app.core.config import settings
from app.core.providers.base import Usage

log = logging.getLogger("obs")

_ENABLED = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
_client = None

if _ENABLED:
    from langfuse import Langfuse, get_client
    # 显式构造单例（v4 构造参数是 base_url；env 变量名是 LANGFUSE_HOST）。
    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_host,
    )
    _client = get_client()
    log.info("Langfuse observability enabled → %s", settings.langfuse_host)


def _strmeta(meta: dict | None) -> dict | None:
    """propagate_attributes 的 metadata 要求值为字符串，这里统一转一下。"""
    return {k: str(v) for k, v in meta.items()} if meta else None


# ── 禁用时的空对象：所有用到的方法都安全 no-op ──────────────────────────────────
class _NullCtx:
    def update(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _NullRoot:
    def update(self, *a, **k): pass
    def update_trace(self, *a, **k): pass

    @contextmanager
    def generation(self, *a, **k):
        yield _NullCtx()

    @contextmanager
    def span(self, *a, **k):
        yield _NullCtx()

    def __enter__(self): return self
    def __exit__(self, *a): return False


# ── 根 observation 的薄封装：把"建子节点 / 设 trace 级 IO"收口在本模块 ─────────────
class _Root:
    def __init__(self, root_obs):
        self._obs = root_obs

    def update_trace(self, **kw):
        # v4：trace 级 input/output 用 set_trace_io（v3 是 update_trace）。
        self._obs.set_trace_io(**kw)

    def update(self, *a, **k):
        self._obs.update(*a, **k)

    @contextmanager
    def generation(self, name: str, *, model=None, input=None):
        """在根下挂一个 generation 子节点（手动、显式串联，跨 yield 安全）。"""
        gen = self._obs.start_observation(
            name=name, as_type="generation", model=model, input=input,
        )
        try:
            yield gen
        finally:
            gen.end()

    @contextmanager
    def span(self, name: str, *, input=None):
        """在根下挂一个普通 span 子节点（查库 / 工具等）。"""
        sp = self._obs.start_observation(name=name, as_type="span", input=input)
        try:
            yield sp
        finally:
            sp.end()


# ── 助手 1：根 trace（一次请求一棵树）──────────────────────────────────────────
@contextmanager
def trace(name: str, *, user_id=None, session_id=None, tags=None,
          metadata=None, input=None):
    """开一条 trace。yield 出 _Root：用 root.generation()/root.span() 建子节点，
    用 root.update_trace(output=...) 收尾。"""
    if not _ENABLED:
        yield _NullRoot()
        return
    from langfuse import propagate_attributes
    # 仅在"建根 observation"这一瞬用 propagate_attributes 把 user/session/tags/metadata
    # 写到 trace 上——这段是纯同步、不跨 yield，attach/detach 在同一 Context 内完成，安全。
    with propagate_attributes(
        user_id=user_id, session_id=session_id,
        tags=tags, metadata=_strmeta(metadata),
    ):
        root_obs = _client.start_observation(name=name, as_type="span", input=input)
    root = _Root(root_obs)
    try:
        yield root                              # ← 流式 yield 发生在 propagate_attributes 之外
    finally:
        root_obs.end()


# ── 助手 2：独立 span（icd.py 用：自身即一条 trace，内部无 yield）──────────────────
@contextmanager
def span(name: str, *, input=None):
    if not _ENABLED:
        yield _NullCtx()
        return
    sp = _client.start_observation(name=name, as_type="span", input=input)
    try:
        yield sp
    finally:
        sp.end()


# ── 把我们的 Usage 写进一个 generation 节点 ────────────────────────────────────
def record_usage(gen, *, output, usage: Usage) -> None:
    """统一封装：把 output、token 用量、成本、实际模型写进 generation。"""
    gen.update(
        output=output,
        model=usage.model or None,
        usage_details={"input": usage.prompt_tokens, "output": usage.completion_tokens},
        # cost_details 用 v4 规范键 total；不传时 Langfuse 也会按 model+usage 自动估算。
        cost_details={"total": usage.cost_usd},
    )


# ── 关停时刷新缓冲（确保最后的 trace 不丢）─────────────────────────────────────
def flush() -> None:
    if _ENABLED and _client is not None:
        _client.flush()
