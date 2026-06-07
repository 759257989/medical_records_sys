# app/schemas/note.py
#
# 病历笔记相关的 Pydantic Schema，定义 API 的请求/响应数据格式。
# 与 app/models/note.py（数据库模型）的区别：
#   - 这里描述"前端传什么、后端返什么"
#   - note.py 描述"数据库表长什么样"

from pydantic import BaseModel


# 医生保存/更新 SOAP 笔记时的请求体格式（对应 PUT /encounters/{id}/note）
# SOAP 是医疗笔记的标准四段式结构：
#   S（Subjective）  主观  —— 患者主诉、自述症状
#   O（Objective）   客观  —— 体检数据、生命体征、检查结果
#   A（Assessment）  评估  —— 医生诊断、鉴别诊断
#   P（Plan）        计划  —— 治疗方案、用药、随访安排
# 四段均有默认空字符串，允许医生只填部分内容就保存（草稿场景）
class NoteSave(BaseModel):
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""