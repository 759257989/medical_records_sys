# app/core/llm.py
#
# 大模型封装层。对外暴露：
#   generate_soap_stream(...)  —— 异步生成“事件”，每个事件是 dict：
#        {"type":"text", "content":"..."}   文本增量
#        {"type":"tool", "label":"..."}     工具被调用的提示（演示用）
#   embed_text / embed_texts   —— 计算向量（ICD 搜索用）
# 没配 OPENAI_API_KEY 时全部走 mock，方便本地把流水线跑通。
import asyncio
import json
from collections.abc import AsyncIterator

from app.core.config import settings

# ── 输出格式契约（拼在模板 system_prompt 后，强制分段）──────────────────────────
OUTPUT_CONTRACT = """
Format the clinical note using EXACTLY these section markers, each on its own line, in this order:
###SUBJECTIVE###
###OBJECTIVE###
###ASSESSMENT###
###PLAN###

Rules:
- In the ASSESSMENT section, include at least one relevant ICD-10 code on its own line,
  formatted as: - <CODE>: <description>
- If prior patient history is provided via the get_patient_history tool, reference relevant
  prior diagnoses or treatments where clinically appropriate.
- Base the note ONLY on the transcript and any provided history. Never invent clinical facts.
  Write "Not documented." where information is missing.
- If the transcript contains no clinically meaningful content, output ONLY:
###INSUFFICIENT###
<one short sentence explaining why>
""".strip()

DEFAULT_PERSONA = "You are an experienced clinical documentation specialist."

# function calling 的工具定义：让模型可以“请求”患者历史。
# 注意参数为空——患者身份后端已知，模型无需（也不能）指定查谁，避免越权。
HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_patient_history",
        "description": (
            "Retrieve this patient's prior encounter notes (assessments and plans) "
            "to inform the current note. Use this for returning patients."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _build_messages(template_prompt: str | None, transcript: str, patient) -> list[dict]:
    system = (template_prompt or DEFAULT_PERSONA) + "\n\n" + OUTPUT_CONTRACT
    user = (
        f"Patient: {patient.first_name} {patient.last_name}, DOB {patient.dob}.\n\n"
        f"Encounter transcript / clinical observations:\n{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# 进程内只建一次客户端。没 key 就为 None → 走 mock。
_client = None
if settings.openai_api_key:
    from openai import AsyncOpenAI
    _client = AsyncOpenAI(api_key=settings.openai_api_key)


async def generate_soap_stream(
    template_prompt: str | None,
    transcript: str,
    patient,
    fetch_history,   # async callable () -> list[dict]，由路由层注入（查 RDS）
    has_history: bool,
) -> AsyncIterator[dict]:
    """逐个产出事件 dict。"""
    # if _client is None:
    #     async for ev in _mock_stream(transcript, fetch_history, has_history):
    #         yield ev
    #     return

    messages = _build_messages(template_prompt, transcript, patient)

    # ── Phase A：复诊患者，强制调用历史工具 ──────────────────────────────────
    if has_history:
        first = await _client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=[HISTORY_TOOL],
            tool_choice={"type": "function", "function": {"name": "get_patient_history"}},
        )
        msg = first.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            history = await fetch_history()                 # ← 真去 RDS 查
            yield {"type": "tool",
                   "label": f"get_patient_history → 取回 {len(history)} 条既往就诊"}
            # 把“模型的工具调用”和“工具返回结果”回灌进对话，让 Phase B 能用上
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(history),
            })

    # ── Phase B：流式产出 SOAP ───────────────────────────────────────────────
    stream = await _client.chat.completions.create(
        model="gpt-4o", messages=messages, stream=True, temperature=0.2,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield {"type": "text", "content": delta}


# ── 向量（ICD 搜索用）────────────────────────────────────────────────────────
async def embed_text(text: str) -> list[float] | None:
    if _client is None:
        return None
    r = await _client.embeddings.create(model="text-embedding-3-small", input=text)
    return r.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    if _client is None:
        return None
    r = await _client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in r.data]