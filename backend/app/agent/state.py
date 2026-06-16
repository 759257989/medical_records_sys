# AgentState：整张图共享的状态。每个节点返回"部分字典"，LangGraph 自动 merge。
# 全部是可 JSON 序列化的简单类型——这样才能被 Postgres checkpointer 存盘/恢复。
from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    # —— 输入(开跑时由 API 注入)——
    encounter_id: str
    provider_id: str
    patient_id: str
    transcript: str
    has_history: bool          # planner 用它决定要不要取既往史

    # —— 过程中逐步填充 ——
    history: list[dict]        # 取到的既往笔记
    icd_candidates: list[dict] # 检索到的候选 ICD：[{code, description, score}]
    draft: str                 # 当前 SOAP 草稿
    critique: str              # 最近一次自我批评意见(重写时喂回给 draft)
    revisions: int             # 已自我批评几次(防死循环计数器)
    assigned_codes: list[dict] # 草稿里的 ICD + 置信度：[{code, confidence, low_confidence}]
    decision: dict             # 人审决定(interrupt 恢复时带回)
    approved_codes: list[dict] # 审批后保留的编码
    final_note: str            # 最终笔记