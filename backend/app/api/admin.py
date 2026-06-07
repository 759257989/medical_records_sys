# app/api/admin.py
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import require_admin           # ★ 整个路由都要管理员权限
from app.core.db import get_db
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.template import Template
from app.models.user import User
from app.schemas.admin import (
    ActiveUpdate, ProviderCreate, ProviderOut,
    TemplateCreate, TemplateFull, TemplateUpdate,
)

# dependencies=[Depends(require_admin)] 让该 router 下每个端点都自动鉴权
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def write_audit(db, admin: User, action: str, entity_type: str, entity_id, details=None):
    """往 audit_log 追加一条记录（不单独提交，跟随业务事务一起 commit）。"""
    db.add(AuditLog(
        user_id=admin.id, action=action,
        entity_type=entity_type, entity_id=entity_id, details=details,
    ))


# ── ADM-1：全局就诊视图（可按 provider + 日期筛选）────────────────────────────
@router.get("/encounters")
async def admin_encounters(
    provider_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    Provider = aliased(User)   # provider 也是 User 表，用别名区分
    conds = []
    if provider_id:
        conds.append(Encounter.provider_id == provider_id)
    if date_from:
        conds.append(Encounter.created_at >= date_from)
    if date_to:
        conds.append(Encounter.created_at < date_to + timedelta(days=1))  # 含当天

    rows = (
        await db.execute(
            select(
                Encounter,
                Patient.first_name, Patient.last_name, Patient.dob,
                Provider.first_name, Provider.last_name,
            )
            .join(Patient, Encounter.patient_id == Patient.id)
            .join(Provider, Encounter.provider_id == Provider.id)
            .where(*conds)
            .order_by(Encounter.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {
            "id": str(e.id), "status": e.status,
            "created_at": e.created_at.isoformat(),
            "patient_name": f"{pf} {pl}", "dob": str(dob),
            "provider_name": f"{prf} {prl}",
        }
        for (e, pf, pl, dob, prf, prl) in rows
    ]


# ── ADM-2/3：医生账号管理 ─────────────────────────────────────────────────────
@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(User).where(User.role == "provider").order_by(User.created_at)
    )
    return list(rows)


@router.post("/providers", response_model=ProviderOut)
async def create_provider(
    body: ProviderCreate,
    admin: User = Depends(require_admin),   # 取到当前管理员用于审计
    db: AsyncSession = Depends(get_db),
):
    exists = await db.scalar(select(User).where(User.email == body.email.lower()))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email_exists")
    u = User(
        email=body.email.lower(), password_hash=hash_password(body.password),
        role="provider", first_name=body.first_name, last_name=body.last_name,
    )
    db.add(u)
    await db.flush()                         # 拿到 u.id
    write_audit(db, admin, "create_provider", "user", u.id, {"email": u.email})
    await db.commit()
    await db.refresh(u)
    return u


@router.patch("/providers/{provider_id}/active", response_model=ProviderOut)
async def set_provider_active(
    provider_id: uuid.UUID,
    body: ActiveUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, provider_id)
    if u is None or u.role != "provider":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="provider_not_found")
    u.is_active = body.is_active
    write_audit(
        db, admin,
        "activate_provider" if body.is_active else "deactivate_provider",
        "user", u.id, None,
    )
    await db.commit()
    await db.refresh(u)
    return u


# ── ADM-4：模板 CRUD（删除用软删除）──────────────────────────────────────────
@router.get("/templates", response_model=list[TemplateFull])
async def admin_list_templates(db: AsyncSession = Depends(get_db)):
    # 含未启用的，但不含已软删除的
    rows = await db.scalars(
        select(Template).where(Template.is_deleted.is_(False)).order_by(Template.name)
    )
    return list(rows)


@router.post("/templates", response_model=TemplateFull)
async def create_template(
    body: TemplateCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    t = Template(
        name=body.name, encounter_type=body.encounter_type,
        system_prompt=body.system_prompt, is_active=body.is_active,
        created_by=admin.id,
    )
    db.add(t)
    await db.flush()
    write_audit(db, admin, "create_template", "template", t.id, {"name": t.name})
    await db.commit()
    await db.refresh(t)
    return t


@router.put("/templates/{template_id}", response_model=TemplateFull)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Template, template_id)
    if t is None or t.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    data = body.model_dump(exclude_unset=True)   # 只取调用方真正传了的字段
    for key, value in data.items():
        setattr(t, key, value)
    write_audit(db, admin, "update_template", "template", t.id, data)
    await db.commit()
    await db.refresh(t)
    return t


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Template, template_id)
    if t is None or t.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")
    t.is_deleted = True                           # ★ 软删除：保历史引用，不物理删
    write_audit(db, admin, "delete_template", "template", t.id, {"name": t.name})
    await db.commit()
    return {"ok": True}


# ── VER-5：审计日志查看 ───────────────────────────────────────────────────────
@router.get("/audit")
async def list_audit(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(AuditLog, User.first_name, User.last_name)
            .outerjoin(User, AuditLog.user_id == User.id)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "action": a.action, "entity_type": a.entity_type,
            "entity_id": str(a.entity_id) if a.entity_id else None,
            "details": a.details, "created_at": a.created_at.isoformat(),
            "actor": f"{fn} {ln}" if fn else "system",
        }
        for (a, fn, ln) in rows
    ]