# app/core/llm.py
#
# 这一层把"如何调用大模型生成 SOAP"封装起来，对外只暴露一个异步生成器
# generate_soap_stream(...)，它逐段 yield 文本增量（token）。
# 路由层只管把这些增量包成 SSE 帧转发，不关心底层是 OpenAI 还是 mock。
import asyncio
from collections.abc import AsyncIterator

from app.core.config import settings

# ── 输出格式契约 ────────────────────────────────────────────────────────────
# 这段拼在每个模板的 system_prompt 后面，强制模型用固定的 ###段### 标记输出，
# 这样前端才能可靠地把流式文本切分到四个分区。
OUTPUT_CONTRACT = """
Format the clinical note using EXACTLY these section markers, each on its own line, in this order:
###SUBJECTIVE###
###OBJECTIVE###
###ASSESSMENT###
###PLAN###

Rules:
- In the ASSESSMENT section, include at least one relevant ICD-10 code on its own line,
  formatted as: - <CODE>: <description>
- Base the note ONLY on the transcript. Never invent clinical facts.
  Write "Not documented." where information is missing.
- If the transcript contains no clinically meaningful content, output ONLY:
###INSUFFICIENT###
<one short sentence explaining why>
""".strip()

# 默认人设：当某次就诊没有选模板时兜底用它。
DEFAULT_PERSONA = "You are an experienced clinical documentation specialist."


def _build_messages(template_prompt: str | None, transcript: str, patient) -> list[dict]:
    """把模板提示 + 输出契约 + 患者信息 + 转录，组装成 OpenAI 的 messages。"""
    system = (template_prompt or DEFAULT_PERSONA) + "\n\n" + OUTPUT_CONTRACT
    user = (
        f"Patient: {patient.first_name} {patient.last_name}, DOB {patient.dob}.\n\n"
        f"Encounter transcript / clinical observations:\n{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# 进程内只创建一次 OpenAI 客户端（有 key 时）。没配 key 就走 mock。
_client = None
if settings.openai_api_key:
    from openai import AsyncOpenAI
    _client = AsyncOpenAI(api_key=settings.openai_api_key)


async def generate_soap_stream(
    template_prompt: str | None, transcript: str, patient
) -> AsyncIterator[str]:
    """异步生成器：逐段产出 SOAP 文本增量。"""
    if _client is None:
        # 没配 OPENAI_API_KEY → 走本地 mock，方便先把整条流水线跑通
        async for delta in _mock_stream(transcript):
            yield delta
        return

    messages = _build_messages(template_prompt, transcript, patient)
    stream = await _client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        stream=True,        # 关键：开启流式
        temperature=0.2,    # 临床文档要稳定、可复现，不要发散
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta


# ── Mock 模式 ───────────────────────────────────────────────────────────────
# 没有 OpenAI key 时用它，把一段写死的 SOAP 按词逐个吐出，模拟真实流式手感。
# 这样你能先验证：SSE 帧、前端逐字渲染、解析归段、保存、版本历史——全部走通。
MOCK_SOAP = """###SUBJECTIVE###
The patient is a 54-year-old male presenting with a 3-day history of productive cough, low-grade fever, and fatigue. He reports mild shortness of breath on exertion but denies chest pain or hemoptysis. No recent travel or sick contacts.

###OBJECTIVE###
Vitals: T 38.1C, HR 92, BP 128/80, RR 18, SpO2 96% on room air. Lungs with scattered rhonchi in the right lower field, no wheezing. Heart regular rate and rhythm. No peripheral edema.

###ASSESSMENT###
Acute bronchitis, likely viral, with no clinical signs of pneumonia at this time.
- J20.9: Acute bronchitis, unspecified
- R05.9: Cough, unspecified

###PLAN###
Supportive care with rest and increased oral fluids. Guaifenesin for symptomatic relief. Return precautions discussed for worsening dyspnea, high fever, or chest pain. Follow up in 7 days if symptoms persist."""


async def _mock_stream(transcript: str) -> AsyncIterator[str]:
    # 转录太短/为空 → 触发"内容不足"分支（Phase 5 边界场景的预演）
    if len((transcript or "").strip()) < 20:
        text = ("###INSUFFICIENT###\n"
                "The transcript does not contain enough clinical information to generate a note.")
    else:
        text = MOCK_SOAP
    for word in text.split(" "):
        yield word + " "
        await asyncio.sleep(0.02)   # 制造逐字流式的视觉效果