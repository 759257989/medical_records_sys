# backend/app/agent/service.py
#
# ═══════════════════════════════════════════════════════════════════════════════
# 这个文件是 agent 的"服务层"：把 LangGraph 图的执行过程翻译成
# 前端能消费的 SSE（Server-Sent Events）事件流。
#
# 【为什么用 SSE 而不是普通 JSON 响应？】
#   agent 跑一次可能需要几秒甚至几十秒（多次 LLM 调用 + 数据库查询），
#   如果等全部跑完再返回，用户盯着空白屏幕等。
#   用 SSE 可以边跑边推送进度：每个节点跑完就立刻告诉前端，
#   前端可以实时显示"正在检索 ICD 编码..."、"正在起草笔记..."等状态。
#
# 【发出的事件类型】
#   {"type": "step", node, updated, ...}       每个节点跑完后推一条进度
#   {"type": "approval_required", ...}         遇到人审 interrupt，暂停并告知前端要展示审批面板
#   {"type": "done", final_note, codes}        图正常跑完，返回最终结果
#   {"type": "error", message}                 遇到死循环或其他异常
#
# 【两种调用场景，对应两个公开函数】
#   start_run(run_id, initial_state)  — 首次运行，传入初始状态从头开始
#   resume_run(run_id, decision)      — 医生审批后，传入审批结果从断点恢复
#
# 【调用链路】
#   FastAPI 路由 (api/encounters.py)
#       ↓ POST /run       → start_run()
#       ↓ POST /approve   → resume_run()
#             ↓
#          _drive()       ← 两者共用的核心驱动逻辑
#             ↓
#     open_checkpointer() ← 连接 Postgres，每步自动存档
#             ↓
#     graph.astream()     ← 流式执行 LangGraph 图，逐节点产出 chunk
#             ↓
#     SSE 事件 yield 给 FastAPI StreamingResponse
# ═══════════════════════════════════════════════════════════════════════════════
from __future__ import annotations

from collections.abc import AsyncIterator

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.agent.checkpointer import open_checkpointer
from app.agent.graph import build_graph

# 硬上限：节点跳转超过这个数 → 抛 GraphRecursionError
# 防止 self_critique ↔ draft 回环失控（正常流程最多 plan+history+icd+draft*3+critique*3+assign+finalize ≈ 12 步）
RECURSION_LIMIT = 25


def _summarize(node: str, update: dict) -> dict:
    """把节点的完整 state 更新压缩成轻量摘要，避免把整段草稿/历史原文塞进每条 SSE 事件。

    前端用这个摘要在时间线上显示"draft 节点更新了 draft 字段"，
    需要看完整内容时再调单独的 GET 接口。
    """
    keys = list(update.keys())      # 记录哪些字段被这个节点更新了
    extra = {}
    if "icd_candidates" in update:
        extra["n_candidates"] = len(update["icd_candidates"])   # 检索到几个候选编码
    if "history" in update:
        extra["n_history"] = len(update["history"])             # 取到几条既往笔记
    if "revisions" in update:
        extra["revisions"] = update["revisions"]                # 当前自我批评轮次
    if "assigned_codes" in update:
        extra["codes"] = [c["code"] for c in update["assigned_codes"]]  # 提取出哪些 ICD 编码
    return {"node": node, "updated": keys, **extra}


async def _drive(stream_input, run_id: str) -> AsyncIterator[dict]:
    """核心驱动：流式运行图，逐节点 yield SSE 事件。

    stream_input 两种形态：
      - dict（初始 AgentState）：从头开始跑
      - Command(resume=...)：从 interrupt 断点恢复，decision 注入为 interrupt() 的返回值
    run_id 对应 thread_id，LangGraph 用它在 Postgres 里找/存对应的 checkpoint。
    """
    # thread_id 是这次会话的唯一标识，checkpointer 用它存档/读档
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}

    async with open_checkpointer() as cp:      # 拿到 Postgres checkpointer，执行期间保持连接
        graph = build_graph(cp)                # 把 checkpointer 绑定到图上，每步自动存档
        try:
            # astream(..., stream_mode="updates")：每个节点执行完立刻 yield 一个 chunk
            # chunk 格式：{"节点名": {该节点对 state 的更新字典}}
            async for chunk in graph.astream(stream_input, config, stream_mode="updates"):

                if "__interrupt__" in chunk:
                    # 图执行到 human_approval 节点的 interrupt() 时，LangGraph 会在 chunk 里
                    # 注入 "__interrupt__" 键，值是 interrupt() 传入的 payload（审批面板数据）。
                    # 此时状态已存入 Postgres，我们把 payload 发给前端，然后 return 结束这次流。
                    # 前端展示审批面板，医生操作后走 /approve → resume_run 恢复。
                    #
                    # 注意：payload 自带一个 "type": "approve_codes" 字段，不能用 {**payload} 直接展开，
                    # 否则它会覆盖掉外层的 "type": "approval_required"，前端就匹配不到审批闸门了。
                    # 这里只挑出前端真正需要的字段，保证事件 type 稳定为 "approval_required"。
                    payload = chunk["__interrupt__"][0].value
                    yield {"type": "approval_required",
                           "low_confidence_codes": payload.get("low_confidence_codes", []),
                           "draft": payload.get("draft", "")}
                    return

                # 普通节点更新：压缩成摘要发给前端做进度展示
                for node, update in chunk.items():
                    yield {"type": "step", **_summarize(node, update)}

        except GraphRecursionError:
            # self_critique ↔ draft 如果出现 bug 导致死循环，RECURSION_LIMIT 会兜底
            yield {"type": "error", "message": "recursion limit hit (possible loop)"}
            return

        # 走到这里说明图正常跑完（没有 interrupt）
        # graph.astream 不直接返回最终 state，需要用 aget_state 单独读
        snap = await graph.aget_state(config)
        yield {"type": "done",
               "final_note": snap.values.get("final_note", ""),
               "approved_codes": snap.values.get("approved_codes", [])}


async def start_run(run_id: str, initial_state: dict) -> AsyncIterator[dict]:
    """首次运行：传入初始 AgentState，图从 plan 节点开始跑。"""
    async for ev in _drive(initial_state, run_id):
        yield ev


async def resume_run(run_id: str, decision: dict) -> AsyncIterator[dict]:
    """医生审批后恢复：decision 是前端提交的审批结果（哪些编码被保留）。

    Command(resume=decision) 会让 LangGraph 从 Postgres 加载上次 interrupt 时的 checkpoint，
    并把 decision 作为 interrupt() 的返回值注入，human_approval 节点接着往下执行。
    """
    async for ev in _drive(Command(resume=decision), run_id):
        yield ev