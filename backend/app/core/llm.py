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
from app.core.providers.base import ChatProvider, Message, ToolSpec
from app.core.providers.mock_provider import MockProvider
from app.core.providers.openai_provider import OpenAIProvider
from app.core.providers.resilience import complete_with_fallback, stream_with_fallback

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


# ── 按已配置的 key 组装 fallback 链：OpenAI → Anthropic → Mock ───────────────────
def _build_chain() -> list[ChatProvider]:
    chain: list[ChatProvider] = []
    if settings.openai_api_key:
        chain.append(OpenAIProvider(settings.openai_api_key))
    if settings.anthropic_api_key:
        chain.append(AnthropicProvider(settings.anthropic_api_key))
    chain.append(MockProvider())     # 永远兜底，保证不硬崩
    return chain


_CHAIN = _build_chain()
# embeddings 只走 OpenAI（Anthropic 没有该接口）。
_EMBED_PROVIDER = OpenAIProvider(settings.openai_api_key) if settings.openai_api_key else MockProvider()


def _build_system_and_messages(template_prompt, transcript, patient):
    system = (template_prompt or DEFAULT_PERSONA) + "\n\n" + OUTPUT_CONTRACT
    user = (
        f"Patient: {patient.first_name} {patient.last_name}, DOB {patient.dob}.\n\n"
        f"Encounter transcript / clinical observations:\n{transcript}"
    )
    return system, [Message(role="user", content=user)]


async def generate_soap_stream(
    template_prompt: str | None,
    transcript: str,
    patient,
    fetch_history,        # async callable () -> list[dict]，由路由层注入（查 RDS）
    has_history: bool,
) -> AsyncIterator[dict]:
    """逐个产出事件 dict（对外形状与原来一致）。"""
    system, messages = _build_system_and_messages(template_prompt, transcript, patient)

    # ── Phase A：复诊患者 → 真发一次强制工具调用，再把历史作为上下文消息追加 ──────────
    if has_history:
        try:
            result = await complete_with_fallback(
                _CHAIN, system=system, messages=messages,
                tools=[HISTORY_TOOL], force_tool="get_patient_history", max_tokens=256,
            )
            log.info("history tool call via provider=%s cost=$%.5f",
                     result.provider, result.usage.cost_usd)
        except Exception as e:                       # noqa: BLE001 工具调用失败不该拖垮生成
            log.warning("history tool phase failed, proceeding without it: %s", e)

        history = await fetch_history()              # 真去 RDS 查
        n = len(history)
        yield {"type": "tool",
               "label": f"Prior encounter history retrieved and incorporated "
                        f"({n} previous visit{'s' if n != 1 else ''})."}
        # provider 无关地把历史注入下一轮上下文（见手册 §3 (A)）。
        messages.append(Message(
            role="user",
            content="Relevant prior encounter history (JSON):\n" + json.dumps(history),
        ))

    # ── Phase B：流式产出 SOAP（带跨 provider fallback）────────────────────────────
    async for delta in stream_with_fallback(_CHAIN, system=system, messages=messages):
        yield {"type": "text", "content": delta}


# ── 向量（ICD 搜索用）——永远走 OpenAI；无 key 返回 None（icd.py 有关键词回退）───────
async def embed_text(text: str) -> list[float] | None:
    out = await _EMBED_PROVIDER.embed([text])
    return out[0] if out else None


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    return await _EMBED_PROVIDER.embed(texts)