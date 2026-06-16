# 图的各个节点。约定：节点是 async 函数，输入 state，输出"部分状态字典"或 Command。
#
# ═══════════════════════════════════════════════════════════════════════════════
# 【节点 vs 路由器】
#   - 节点 (Node)：async 函数，由 graph.add_node("name", fn) 注册到 StateGraph。
#     LangGraph 每次执行该节点时调用它，传入当前完整 AgentState，返回值会被 merge
#     回 state（partial update）。
#   - 条件路由器 (Conditional Edge)：普通同步函数，返回字符串（下一个节点名）。
#     由 graph.add_conditional_edges("src", fn) 注册，不修改 state，只决定走哪条边。
#
# 【本文件的节点清单（按执行顺序）】
#   plan            → 节点：检查 has_history，决定先取史料还是直接检索 ICD
#   retrieve_history → 节点：调 tools.fetch_history 取患者既往笔记
#   retrieve_icd    → 节点：调 tools.search_icd 检索候选 ICD-10 编码
#   draft           → 节点：让 LLM 起草 SOAP 笔记（可携带批评意见重写）
#   self_critique   → 节点：让 LLM 自查草稿质量，决定"重写"或"放行"
#   assign_codes    → 节点：从草稿提取 ICD 编码，结合检索分数判断置信度
#   human_approval  → 节点：interrupt() 暂停图，等医生在前端审批低置信编码
#   finalize        → 节点：汇总最终笔记和已批准编码，写入 state
#
#   needs_approval  → 条件路由器（不是节点）：有低置信编码 → human_approval，否则 → finalize
#
# 【调用链路】
#   1. FastAPI 路由（如 POST /api/encounters/{id}/run）收到请求
#   2. 调用 graph.ainvoke(input_state, {"configurable": {"thread_id": encounter_id}})
#   3. LangGraph 从 Postgres checkpointer 加载该 thread 的最新快照（若无则从头开始）
#   4. 按图的边顺序依次调用本文件中的节点函数
#   5. 每个节点执行后，返回值 merge 入 AgentState，并存一次 Postgres 快照（checkpoint）
#   6. 遇到 interrupt() → 图暂停，HTTP 响应返回给前端（携带审批 payload）
#   7. 医生操作后，前端调 POST /api/encounters/{id}/approve，
#      后端调 graph.ainvoke(Command(resume=decision), config) 从断点恢复
#   8. finalize 节点执行完毕，图结束，最终 state 持久化到 Postgres
#
# 【执行图（有向图结构，在 graph.py 中用 StateGraph 组装）】
#
#   ┌─────START──────┐
#   │     plan       │
#   └────────────────┘
#        ↙        ↘
#   has_history   !has_history
#        ↓              ↓
#   retrieve_       retrieve_
#   history  ───→   icd
#                    ↓
#                  draft  ←──────────────────┐
#                    ↓                       │ needs_revision && revisions < MAX
#               self_critique ───────────────┘
#                    ↓ (ok)
#               assign_codes
#                    ↓
#              needs_approval()  ← 条件路由器
#               ↙          ↘
#         human_           finalize
#         approval
#              ↓
#           finalize
#              ↓
#            END
# ═══════════════════════════════════════════════════════════════════════════════
import json
import re
from typing import Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt

from app.agent import tools
from app.agent.state import AgentState
from app.core.llm import _CHAIN                          # 复用 Phase 0 的 provider 弹性链
from app.core.llm import OUTPUT_CONTRACT, DEFAULT_PERSONA
from app.core.providers.base import Message, ToolSpec
from app.core.providers.resilience import complete_with_fallback

MAX_REVISIONS = 2          # 自我批评最多回环 2 次(防死循环的"软"上限)
CONFIDENCE_MIN = 0.5       # ICD 检索分数低于此 → 视为低置信度，需人审
ICD_LINE = re.compile(r"- ([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?): *(.*)")  # 组1=编码 组2=描述


# ── plan：决定路径(工具选择的雏形)——有既往史才去取，否则跳过 ────────────────────
async def plan(state: AgentState) -> Command[Literal["retrieve_history", "retrieve_icd"]]:
    goto = "retrieve_history" if state.get("has_history") else "retrieve_icd"
    # Command 同时"更新状态 + 指定下一步"，比单独写条件边更紧凑
    return Command(update={"revisions": 0}, goto=goto)


# ── retrieve_history：调工具取既往史 ────────────────────────────────────────────
async def retrieve_history(state: AgentState) -> dict:
    history = await tools.fetch_history(state["patient_id"], state["encounter_id"])
    return {"history": history}


# ── retrieve_icd：用转录做检索，拿候选编码 ──────────────────────────────────────
async def retrieve_icd(state: AgentState) -> dict:
    candidates = await tools.search_icd(state["transcript"][:500])
    return {"icd_candidates": candidates}


# ── draft：起草 SOAP；若带着批评意见(重写),把意见也喂进去 ────────────────────────
async def draft(state: AgentState) -> dict:
    system = DEFAULT_PERSONA + "\n\n" + OUTPUT_CONTRACT
    parts = [f"Encounter transcript:\n{state['transcript']}"]
    if state.get("history"):
        parts.append("Relevant prior history (JSON):\n" + json.dumps(state["history"]))
    if state.get("icd_candidates"):
        codes = [f"{c['code']}: {c['description']}" for c in state["icd_candidates"]]
        parts.append("Candidate ICD-10 codes (pick the clinically appropriate ones):\n"
                     + "\n".join(codes))
    if state.get("critique"):                            # 这是"重写"——把上轮批评意见带上
        parts.append("Revise the previous draft to address this critique:\n" + state["critique"])
    result = await complete_with_fallback(
        _CHAIN, system=system,
        messages=[Message(role="user", content="\n\n".join(parts))], max_tokens=1200,
    )
    return {"draft": result.text}


# ── self_critique：模型自查 → 决定"重写"还是"放行"(带次数上限的回环)────────────────
_CRITIQUE_TOOL = ToolSpec(
    name="submit_review",
    description="Submit the self-review of the draft note.",
    parameters={
        "type": "object",
        "properties": {
            "needs_revision": {"type": "boolean"},
            "critique": {"type": "string", "description": "What to fix; empty if fine."},
        },
        "required": ["needs_revision", "critique"],
    },
)

async def self_critique(state: AgentState) -> Command[Literal["draft", "assign_codes"]]:
    res = await complete_with_fallback(
        _CHAIN,
        system=("You are a meticulous clinical-note reviewer. Check the NOTE against the "
                "TRANSCRIPT for missing key info, unsupported claims, and format issues. "
                "Call submit_review."),
        messages=[Message(role="user",
                          content=f"TRANSCRIPT:\n{state['transcript']}\n\nNOTE:\n{state['draft']}")],
        tools=[_CRITIQUE_TOOL], force_tool="submit_review", max_tokens=400,
    )
    verdict = res.tool_calls[0].arguments if res.tool_calls else {"needs_revision": False}
    revisions = state.get("revisions", 0)
    # 需要修订 且 没到上限 → 回到 draft(计数 +1)；否则 → 进入定编码
    if verdict.get("needs_revision") and revisions < MAX_REVISIONS:
        return Command(update={"critique": verdict.get("critique", ""),
                               "revisions": revisions + 1}, goto="draft")
    return Command(update={"critique": ""}, goto="assign_codes")


# ── assign_codes：从草稿提取 ICD，对照检索分数算置信度 ──────────────────────────────
async def assign_codes(state: AgentState) -> dict:
    by_code = {c["code"]: c for c in state.get("icd_candidates", [])}
    assigned = []
    for m in ICD_LINE.finditer(state.get("draft", "")):
        code = m.group(1)
        cand = by_code.get(code)                          # 草稿里的编码是否在检索候选里？
        score = cand["score"] if cand and cand.get("score") is not None else None
        # 名称：优先用检索候选里的规范描述，否则退回草稿行里模型写的描述
        description = (cand["description"] if cand and cand.get("description")
                       else (m.group(2) or "").strip())
        low = (score is None) or (score < CONFIDENCE_MIN) # 没检索到 / 分数低 → 低置信
        assigned.append({"code": code, "description": description,
                         "confidence": score, "low_confidence": low})
    return {"assigned_codes": assigned}


# ── 路由：有低置信度编码就走人审，否则直接定稿 ────────────────────────────────────
def needs_approval(state: AgentState) -> Literal["human_approval", "finalize"]:
    return "human_approval" if any(c["low_confidence"] for c in state.get("assigned_codes", [])) \
        else "finalize"


# ── human_approval：停下来等人(HITL 的核心)────────────────────────────────────────
async def human_approval(state: AgentState) -> dict:
    low = [c for c in state["assigned_codes"] if c["low_confidence"]]
    # interrupt() 会让图在此暂停，状态存进 Postgres；前端拿到这个 payload 去渲染审批面板。
    # 医生点完后，API 用 Command(resume=...) 恢复，interrupt() 的返回值就是医生的决定。
    decision = interrupt({
        "type": "approve_codes",
        "low_confidence_codes": low,
        "draft": state["draft"],
    })
    approved_set = set(decision.get("approved", []))     # 医生勾选保留的低置信编码
    approved = [c for c in state["assigned_codes"]
                if (not c["low_confidence"]) or c["code"] in approved_set]
    return {"decision": decision, "approved_codes": approved}


# ── finalize：产出最终笔记 ─────────────────────────────────────────────────────
async def finalize(state: AgentState) -> dict:
    # 没经过人审的情况下，approved_codes 还没填 → 用全部 assigned 作为已认可
    approved = state.get("approved_codes") or state.get("assigned_codes", [])
    return {"final_note": state["draft"], "approved_codes": approved}