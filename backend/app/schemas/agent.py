# backend/app/schemas/agent.py
from pydantic import BaseModel


class StartRunBody(BaseModel):
    transcript: str


class ApproveBody(BaseModel):
    approved: list[str] = []        # 医生决定保留的低置信 ICD 编码(其余视为驳回)