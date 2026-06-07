# app/api/encounters.py
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_encounter
from app.core.db import get_db
from app.core.llm import generate_soap_stream
from app.models.encounter import Encounter
from app.models.note import NoteVersion
from app.models.patient import Patient
from app.models.template import Template
from app.models.user import User
from app.schemas.encounter import EncounterCreate, GenerateRequest
from app.schemas.note import NoteSave

router = APIRouter(prefix="/api/encounters", tags=["encounters"])


# ── ① 新建就诊（find-or-create 患者）──────────────────────────────────────────
@router.post("")
async def create_encounter(
    body: EncounterCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 按 名+姓（大小写不敏感）+ 出生日期 查找已有患者
    patient = await db.scalar(
        select(Patient).where(
            func.lower(Patient.first_name) == body.first_name.lower(),
            func.lower(Patient.last_name) == body.last_name.lower(),
            Patient.dob == body.dob,
        )
    )
    is_returning = patient is not None     # 是否复诊患者（Phase 3 会用到）
    if patient is None:
        patient = Patient(
            first_name=body.first_name, last_name=body.last_name, dob=body.dob
        )
        db.add(patient)
        await db.flush()                   # flush 后能拿到 patient.id（还没 commit）

    enc = Encounter(
        patient_id=patient.id,
        provider_id=user.id,               # 归属当前登录医生
        template_id=body.template_id,
        status="draft",
    )
    db.add(enc)
    await db.commit()
    await db.refresh(enc)

    return {
        "id": str(enc.id),
        "status": enc.status,
        "template_id": str(enc.template_id) if enc.template_id else None,
        "is_returning": is_returning,
        "patient": {
            "id": str(patient.id),
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "dob": str(patient.dob),
        },
    }


# ── ② 流式生成 SOAP（SSE） ─────────────────────────────────────────────────
@router.post("/{encounter_id}/generate")
async def generate(
    body: GenerateRequest,
    encounter: Encounter = Depends(get_owned_encounter),  # 自动校验归属
    db: AsyncSession = Depends(get_db),
):
    # 1) 修改内存中的 ORM 对象（即使生成中断，转录也不丢）
    encounter.transcript = body.transcript
    encounter.status = "generated"

    # 2) 实时读取该就诊选定的模板（支持 Phase 4 的"改了立即生效"）
    template_prompt = None
    if encounter.template_id:
        tmpl = await db.get(Template, encounter.template_id)
        template_prompt = tmpl.system_prompt if tmpl else None

    # 3) 取患者信息（拼进给模型的上下文）
    patient = await db.get(Patient, encounter.patient_id)
    await db.commit()

    # 4) 定义 SSE 事件流：把模型增量逐帧发给浏览器
    async def event_stream():
        try:
            async for delta in generate_soap_stream(template_prompt, body.transcript, patient):
                # SSE 帧格式：data: <内容>\n\n。用 JSON 包一层，避免 token 里的换行破坏帧。
                yield f"data: {json.dumps({'t': delta})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:  # 生成出错也通过流告诉前端，前端可优雅提示
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── ③ 保存笔记（追加新版本，永不覆盖 ─────────────────────────────────────
@router.post("/{encounter_id}/notes")
async def save_note(
    body: NoteSave,
    encounter: Encounter = Depends(get_owned_encounter),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 取当前该 encounter 的最大版本号，+1 作为新版本号
    max_v = await db.scalar(
        select(func.max(NoteVersion.version_no)).where(
            NoteVersion.encounter_id == encounter.id
        )
    )
    next_v = (max_v or 0) + 1

    nv = NoteVersion(
        encounter_id=encounter.id,
        version_no=next_v,
        subjective=body.subjective,
        objective=body.objective,
        assessment=body.assessment,
        plan=body.plan,
        created_by=user.id,         # 记录"谁"保存
    )
    db.add(nv)
    encounter.status = "finalized"
    await db.commit()
    await db.refresh(nv)

    return {
        "id": str(nv.id),
        "version_no": nv.version_no,
        "created_at": nv.created_at.isoformat(),
    }


# ── ④ 版本历史（含保存人、时间）───────────────────────────────────────────────
@router.get("/{encounter_id}/notes")
async def list_notes(
    encounter: Encounter = Depends(get_owned_encounter),
    db: AsyncSession = Depends(get_db),
):
    # 关联 users 表，把保存人的姓名一起查出来
    rows = (
        await db.execute(
            select(NoteVersion, User.first_name, User.last_name)
            .join(User, NoteVersion.created_by == User.id)
            .where(NoteVersion.encounter_id == encounter.id)
            .order_by(NoteVersion.version_no.desc())   # 最新版本在前
        )
    ).all()

    return [
        {
            "id": str(nv.id),
            "version_no": nv.version_no,
            "subjective": nv.subjective,
            "objective": nv.objective,
            "assessment": nv.assessment,
            "plan": nv.plan,
            "created_at": nv.created_at.isoformat(),
            "author_name": f"{fn} {ln}",
        }
        for (nv, fn, ln) in rows
    ]