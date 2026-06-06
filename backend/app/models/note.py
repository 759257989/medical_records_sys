# app/models/note.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# NoteVersion：病历笔记的不可变版本历史表。
# 每次医生保存或 AI 生成笔记，都追加一条新记录而非覆盖旧数据，
# 从而保留完整审计轨迹（谁、在何时、写了什么），满足医疗合规要求。
# 当前有效版本 = 同一 encounter_id 下 version_no 最大的那条。
class NoteVersion(Base):
    __tablename__ = "note_versions"
    # 同一 encounter 下版本号唯一 —— 从数据库层面保证”追加式、永不覆盖”
    __table_args__ = (UniqueConstraint("encounter_id", "version_no", name="uq_note_enc_ver"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # 主键，UUID v4
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"), nullable=False)      # 归属的就诊记录
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)   # 版本序号，从 1 开始递增；最大值为当前版本
    subjective: Mapped[str | None] = mapped_column(Text)   # S（主观）：患者主诉、症状描述
    objective: Mapped[str | None] = mapped_column(Text)    # O（客观）：体检结果、生命体征、检查数据
    assessment: Mapped[str | None] = mapped_column(Text)   # A（评估）：诊断结论、鉴别诊断
    plan: Mapped[str | None] = mapped_column(Text)         # P（计划）：治疗方案、用药、随访安排
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)             # 保存本版本的用户（医生或系统 AI）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # 本版本的保存时间，不可修改


# NoteVersionCode：笔记版本与 ICD-10 诊断编码的多对多关联表。
# 每个版本可关联多个诊断码，同一版本下每个编码只出现一次（联合主键保证）。
# 版本迭代时重新写入该版本对应的编码集合，旧版本的编码记录保持不变。
class NoteVersionCode(Base):
    __tablename__ = "note_version_codes"

    note_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("note_versions.id"), primary_key=True)  # 关联的笔记版本
    icd10_code_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("icd10_codes.id"), primary_key=True)      # 关联的 ICD-10 诊断编码