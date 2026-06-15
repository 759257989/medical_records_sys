# backend/app/core/llm.py
#
# 大模型门面层（facade）。对外暴露与原来完全一致的接口：
#   generate_soap_stream(...)  逐个产出事件 dict（{"type":"text"|"tool", ...}）
#   embed_text / embed_texts   ICD 向量检索用
# 内部：组装 provider 列表 → 走 resilience（重试 + 跨厂商 fallback）→ 记 token/成本。
import json
import logging
from collections.abc import AsyncIterator

from app.core.config import settings
from app.core.providers.anthropic_provider import AnthropicProvider
from app.core.providers.base import ChatProvider, Message, ToolSpec, Usage
from app.core.providers.mock_provider import MockProvider
from app.core.providers.openai_provider import OpenAIProvider
from app.core.providers.resilience import complete_with_fallback, stream_with_fallback
from app.core.observability.tracing import trace, record_usage
from app.core import prompts as prompt_registry 

log = logging.getLogger("llm")

# ── 输出格式契约（与原文件一致，拼到 system 末尾，强制分段）────────────────────────
OUTPUT_CONTRACT = """
Format the clinical note using EXACTLY these section markers, each on its own line, in this order:
###SUBJECTIVE###
###OBJECTIVE###
###ASSESSMENT###
###PLAN###

Rules:
- In the ASSESSMENT section, include at least one relevant ICD-10 code on its own line,
  formatted as: - <CODE>: <description>
- If prior patient history is provided, reference relevant prior diagnoses or treatments
  where clinically appropriate.
- Base the note ONLY on the transcript and any provided history. Never invent clinical facts.
  Write "Not documented." where information is missing.
- If the transcript contains no clinically meaningful content, output ONLY:
###INSUFFICIENT###
<one short sentence explaining why>
""".strip()

DEFAULT_PERSONA = "You are an experienced clinical documentation specialist."

# 归一化的历史工具定义（保留"function calling"叙事）。参数为空——后端已知患者身份。
HISTORY_TOOL = ToolSpec(
    name="get_patient_history",
    description=(
        "Retrieve this patient's prior encounter notes (assessments and plans) "
        "to inform the current note. Use this for returning patients."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
)

# llm.py —— 用一个 {名字: provider} 注册表，支持"指定谁当主力"
def _build_providers() -> dict[str, ChatProvider]:
    providers: dict[str, ChatProvider] = {}
    if settings.openai_api_key:
        providers["openai"] = OpenAIProvider(settings.openai_api_key)
    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(settings.anthropic_api_key)
    providers["mock"] = MockProvider()              # 永远兜底
    return providers

_PROVIDERS = _build_providers()
# 默认链(champion 优先)：openai → anthropic → mock，给 embed/judge 等复用
_CHAIN = [p for n in ("openai", "anthropic", "mock") if (p := _PROVIDERS.get(n))]

# ── 按已配置的 key 组装 fallback 链：OpenAI → Anthropic → Mock ───────────────────
def build_chain(primary: str | None = None) -> list[ChatProvider]:
    """把 primary 排到 fallback 链最前；其余 provider 仍作为回退兜底。"""
    if not primary or primary not in _PROVIDERS:
        return _CHAIN
    rest = [p for n, p in _PROVIDERS.items() if n != primary]
    return [_PROVIDERS[primary], *rest]


# embeddings 只走 OpenAI（Anthropic 没有该接口）。
_EMBED_PROVIDER = OpenAIProvider(settings.openai_api_key) if settings.openai_api_key else MockProvider()


def _build_system_and_messages(template_prompt, transcript, patient, version=None):
    if template_prompt:
        persona = template_prompt
    else:
        try:
            persona = prompt_registry.load(version)      # ← 用治理解析出的版本
        except FileNotFoundError:
            persona = DEFAULT_PERSONA
    system = persona + "\n\n" + OUTPUT_CONTRACT
    user = (
        f"Patient: {patient.first_name} {patient.last_name}, DOB {patient.dob}.\n\n"
        f"Encounter transcript / clinical observations:\n{transcript}"
    )
    return system, [Message(role="user", content=user)]


async def generate_soap_stream(
    template_prompt, transcript, patient, fetch_history, has_history,
    trace_meta=None,
    prompt_version: str | None = None,      # ← 新增：用哪个 prompt 版本
    primary_provider: str | None = None,    # ← 新增：哪个 provider 当主力(champion/challenger)
):
    trace_meta = trace_meta or {}
    system, messages = _build_system_and_messages(template_prompt, transcript, patient, prompt_version)
    chain = build_chain(primary_provider)   # ← 按治理决策构链；未指定则用默认 _CHAIN

    with trace(
        "generate_soap",
        user_id=trace_meta.get("provider_id"),
        session_id=trace_meta.get("encounter_id"),
        # tags 里带上 版本 和 arm —— Phase 1 的 Langfuse 里就能按它们分组对比 A/B
        tags=["soap", prompt_version or settings.prompt_version, trace_meta.get("model_arm", "champion")],
        metadata={"prompt_version": prompt_version or settings.prompt_version,
                  "model_arm": trace_meta.get("model_arm"), "has_history": has_history},
        input={"transcript": transcript[:1000]},
    ) as root:

        # ── Phase A：复诊 → 强制工具调用（记成一个 generation）────────────────────
        if has_history:
            with root.generation("history_tool_call", model="gpt-4o",
                                 input={"tool": "get_patient_history"}) as gen:
                try:
                    result = await complete_with_fallback(
                        chain, system=system, messages=messages,
                        tools=[HISTORY_TOOL], force_tool="get_patient_history", max_tokens=256,
                    )
                    record_usage(gen, output=[tc.name for tc in result.tool_calls],
                                 usage=result.usage)
                except Exception as e:                      # noqa: BLE001
                    log.warning("history tool phase failed, proceeding without it: %s", e)

            history = await fetch_history()
            with root.span("fetch_patient_history") as sp:    # 查库记成一个普通 span
                sp.update(output={"visits": len(history)})

            n = len(history)
            yield {"type": "tool",
                   "label": f"Prior encounter history retrieved and incorporated "
                            f"({n} previous visit{'s' if n != 1 else ''})."}
            messages.append(Message(
                role="user",
                content="Relevant prior encounter history (JSON):\n" + json.dumps(history),
            ))

        # ── Phase B：流式产出（记成一个 generation，回填流式用量）────────────────
        usage = Usage()
        parts: list[str] = []
        with root.generation("soap_generation",
                             input={"messages": [m.content for m in messages]}) as gen:
            async for delta in stream_with_fallback(
                chain, system=system, messages=messages, usage_sink=usage,
            ):
                parts.append(delta)
                yield {"type": "text", "content": delta}
            record_usage(gen, output="".join(parts), usage=usage)

        root.update_trace(output={"chars": len("".join(parts))})


# ── 向量（ICD 搜索用）——永远走 OpenAI；无 key 返回 None（icd.py 有关键词回退）───────
async def embed_text(text: str) -> list[float] | None:
    out = await _EMBED_PROVIDER.embed([text])
    return out[0] if out else None


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    return await _EMBED_PROVIDER.embed(texts)


# ── 离线(非流式)生成：评估 harness 专用 ─────────────────────────────────────────
# 复用与生产完全相同的 system(persona + OUTPUT_CONTRACT)和 user 拼装方式，
# 只是不流式、不开 trace。这样"评估看到的 prompt"== "生产看到的 prompt"。
async def generate_note(transcript: str, history: list[dict] | None = None) -> str:
    from types import SimpleNamespace
    # 评估不关心患者身份，用占位对象复用 _build_system_and_messages 的拼装逻辑。
    patient = SimpleNamespace(first_name="Eval", last_name="Patient", dob="1990-01-01")
    system, messages = _build_system_and_messages(None, transcript, patient)
    if history:                                   # 复诊场景：把历史按生产同样的格式喂进去
        messages.append(Message(
            role="user",
            content="Relevant prior encounter history (JSON):\n" + json.dumps(history),
        ))
    result = await complete_with_fallback(
        _CHAIN, system=system, messages=messages, max_tokens=1200,
    )
    return result.text