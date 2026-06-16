# 把节点连成 StateGraph。注意：图结构是静态的，但 checkpointer 是运行时传入的，
# 所以这里提供一个"给定 checkpointer，编译出图"的工厂函数。
from langgraph.graph import StateGraph, START, END

from app.agent import nodes
from app.agent.state import AgentState


def build_graph(checkpointer):
    g = StateGraph(AgentState)

    # 注册节点
    g.add_node("plan", nodes.plan)
    g.add_node("retrieve_history", nodes.retrieve_history)
    g.add_node("retrieve_icd", nodes.retrieve_icd)
    g.add_node("draft", nodes.draft)
    g.add_node("self_critique", nodes.self_critique)
    g.add_node("assign_codes", nodes.assign_codes)
    g.add_node("human_approval", nodes.human_approval)
    g.add_node("finalize", nodes.finalize)

    # 连边。plan / self_critique 用 Command 自己跳转，无需在这里写它们的出边。
    g.add_edge(START, "plan")
    g.add_edge("retrieve_history", "retrieve_icd")   # 取完既往史 → 检索 ICD
    g.add_edge("retrieve_icd", "draft")
    g.add_edge("draft", "self_critique")             # 起草后必自查
    # assign_codes 之后按"有无低置信编码"分流
    g.add_conditional_edges("assign_codes", nodes.needs_approval,
                            {"human_approval": "human_approval", "finalize": "finalize"})
    g.add_edge("human_approval", "finalize")
    g.add_edge("finalize", END)

    # 编译时绑定 checkpointer —— 这一步让整张图"可持久化、可暂停恢复"
    return g.compile(checkpointer=checkpointer)