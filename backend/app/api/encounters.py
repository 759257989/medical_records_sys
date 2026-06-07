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
from app.schemas.encounter import DraftSave, EncounterCreate, GenerateRequest
from app.schemas.note import NoteSave

router = APIRouter(prefix="/api/encounters", tags=["encounters"])


# ── 工具函数：查某患者“别的就诊”里的既往笔记（每个就诊取最新版本）────────────────
async def query_patient_history(db: AsyncSession, patient_id, exclude_encounter_id):
    rows = (
        await db.execute(
            select(NoteVersion, Encounter.created_at)
            .join(Encounter, NoteVersion.encounter_id == Encounter.id)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.id != exclude_encounter_id,   # 排除当前这次
            )
            .order_by(Encounter.created_at.desc(), NoteVersion.version_no.desc())
        )
    ).all()

    seen, history = set(), []
    for nv, created in rows:
        if nv.encounter_id in seen:      # 同一就诊只取最新版本
            continue
        seen.add(nv.encounter_id)
        history.append({
            "date": created.date().isoformat(),
            "assessment": nv.assessment,
            "plan": nv.plan,
        })
    return history[:5]                    # 最多带最近 5 次


async def _history_count(db: AsyncSession, patient_id, exclude_encounter_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(NoteVersion)
        .join(Encounter, NoteVersion.encounter_id == Encounter.id)
        .where(
            Encounter.patient_id == patient_id,
            Encounter.id != exclude_encounter_id,
        )
    ) or 0


# ── ① 新建就诊（find-or-create 患者）─────────────────────────────────────────
@router.post("")
async def create_encounter(
    body: EncounterCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.scalar(
        select(Patient).where(
            func.lower(Patient.first_name) == body.first_name.lower(),
            func.lower(Patient.last_name) == body.last_name.lower(),
            Patient.dob == body.dob,
        )
    )
    is_returning = patient is not None
    if patient is None:
        patient = Patient(first_name=body.first_name, last_name=body.last_name, dob=body.dob)
        db.add(patient)
        await db.flush()

    enc = Encounter(
        patient_id=patient.id, provider_id=user.id,
        template_id=body.template_id, status="draft",
    )
    db.add(enc)
    await db.commit()
    await db.refresh(enc)

    return {
        "id": str(enc.id), "status": enc.status,
        "template_id": str(enc.template_id) if enc.template_id else None,
        "is_returning": is_returning,
        "patient": {
            "id": str(patient.id), "first_name": patient.first_name,
            "last_name": patient.last_name, "dob": str(patient.dob),
        },
    }


# ── “我的未完成就诊”列表（供 Dashboard 恢复用）★ 必须放在 /{encounter_id} 之前 ──
@router.get("/mine")
async def my_encounters(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Encounter, Patient.first_name, Patient.last_name, Patient.dob)
            .join(Patient, Encounter.patient_id == Patient.id)
            .where(Encounter.provider_id == user.id, Encounter.status != "finalized")
            .order_by(Encounter.updated_at.desc())
            .limit(20)
        )
    ).all()
    return [
        {
            "id": str(e.id), "status": e.status,
            "updated_at": e.updated_at.isoformat(),
            "patient_name": f"{fn} {ln}", "dob": str(dob),
            "has_transcript": bool(e.transcript),
        }
        for (e, fn, ln, dob) in rows
    ]


# ── 取单条就诊的完整状态（供刷新/换设备恢复）────────────────────────────────────
@router.get("/{encounter_id}")
async def get_encounter(
    encounter: Encounter = Depends(get_owned_encounter),
    db: AsyncSession = Depends(get_db),
):
    patient = await db.get(Patient, encounter.patient_id)
    hist = await _history_count(db, patient.id, encounter.id)
    return {
        "id": str(encounter.id), "status": encounter.status,
        "template_id": str(encounter.template_id) if encounter.template_id else None,
        "transcript": encounter.transcript or "",
        "working_note": encounter.working_note or {},
        "is_returning": hist > 0,
        "patient": {
            "id": str(patient.id), "first_name": patient.first_name,
            "last_name": patient.last_name, "dob": str(patient.dob),
        },
    }


# ── 草稿自动保存（autosave）──────────────────────────────────────────────────
@router.put("/{encounter_id}/draft")
async def save_draft(
    body: DraftSave,
    encounter: Encounter = Depends(get_owned_encounter),
    db: AsyncSession = Depends(get_db),
):
    if body.transcript is not None:
        encounter.transcript = body.transcript
    if body.working_note is not None:
        encounter.working_note = body.working_note
    await db.commit()
    return {"ok": True}


# ── ② 流式生成 SOAP（含历史注入）─────────────────────────────────────────────
@router.post("/{encounter_id}/generate")
async def generate(
    body: GenerateRequest,
    encounter: Encounter = Depends(get_owned_encounter),
    db: AsyncSession = Depends(get_db),
):
    encounter.transcript = body.transcript     # 先存转录，永不丢
    encounter.status = "generated"

    template_prompt = None
    if encounter.template_id:
        tmpl = await db.get(Template, encounter.template_id)
        template_prompt = tmpl.system_prompt if tmpl else None

    patient = await db.get(Patient, encounter.patient_id)
    has_history = (await _history_count(db, patient.id, encounter.id)) > 0
    await db.commit()

    # 闭包：工具被调用时才真正去查历史（在生成期间发生）
    pid, eid = patient.id, encounter.id

    async def fetch_history():
        return await query_patient_history(db, pid, eid)

    async def event_stream():
        try:
            async for ev in generate_soap_stream(
                template_prompt, body.transcript, patient, fetch_history, has_history
            ):
                yield f"data: {json.dumps(ev)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── ③ 保存笔记（追加新版本）──────────────────────────────────────────────────
@router.post("/{encounter_id}/notes")
async def save_note(
    body: NoteSave,
    encounter: Encounter = Depends(get_owned_encounter),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    max_v = await db.scalar(
        select(func.max(NoteVersion.version_no)).where(
            NoteVersion.encounter_id == encounter.id
        )
    )
    next_v = (max_v or 0) + 1
    nv = NoteVersion(
        encounter_id=encounter.id, version_no=next_v,
        subjective=body.subjective, objective=body.objective,
        assessment=body.assessment, plan=body.plan, created_by=user.id,
    )
    db.add(nv)
    encounter.status = "finalized"
    await db.commit()
    await db.refresh(nv)
    return {"id": str(nv.id), "version_no": nv.version_no, "created_at": nv.created_at.isoformat()}


# ── ④ 版本历史 ───────────────────────────────────────────────────────────────
@router.get("/{encounter_id}/notes")
async def list_notes(
    encounter: Encounter = Depends(get_owned_encounter),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(NoteVersion, User.first_name, User.last_name)
            .join(User, NoteVersion.created_by == User.id)
            .where(NoteVersion.encounter_id == encounter.id)
            .order_by(NoteVersion.version_no.desc())
        )
    ).all()
    return [
        {
            "id": str(nv.id), "version_no": nv.version_no,
            "subjective": nv.subjective, "objective": nv.objective,
            "assessment": nv.assessment, "plan": nv.plan,
            "created_at": nv.created_at.isoformat(),
            "author_name": f"{fn} {ln}",
        }
        for (nv, fn, ln) in rows
    ]