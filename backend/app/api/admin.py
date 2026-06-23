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
# app/api/admin.py 追加
from app.models.prompt_version import PromptVersion
from app.models.model_routing import ModelRouting
from app.schemas.admin import PromptVersionOut, ModelRoutingOut, ModelRoutingUpdate
from app.api.deps import get_current_user

from app.models.tenant import Tenant
from app.api.deps import get_current_user

# dependencies=[Depends(require_admin)] 让该 router 下每个端点都自动鉴权
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def write_audit(db, admin: User, action: str, entity_type: str, entity_id, details=None):
    """往 audit_log 追加一条记录（不单独提交，跟随业务事务一起 commit）。"""
    db.add(AuditLog(
        user_id=admin.id, action=action,
        entity_type=entity_type, entity_id=entity_id, details=details,
        tenant_id=admin.tenant_id,
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
        created_by=admin.id, tenant_id=admin.tenant_id,
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


# ── 治理：prompt 版本注册表 + eval-gated 晋升 / 回滚 ──────────────────────────────
# 晋升闸门看的指标(都是"越大越好")
GATE_KEYS = ["structured_output.pass_rate", "faithfulness.faithful_rate", "task_success.pass_rate"]


@router.get("/prompts", response_model=list[PromptVersionOut])
async def list_prompt_versions(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PromptVersion).order_by(PromptVersion.name))).scalars().all()
    return rows


@router.post("/prompts/{name}/promote", response_model=PromptVersionOut)
async def promote_prompt(
    name: str,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    candidate = await db.scalar(select(PromptVersion).where(PromptVersion.name == name))
    if candidate is None or candidate.scorecard is None:
        raise HTTPException(400, "该版本不存在或还没有评分卡(先跑 score_version)")

    current = await db.scalar(select(PromptVersion).where(PromptVersion.status == "production"))

    # ── eval-gate：逐指标对比候选 vs 现任 champion ──
    deltas, blocked = {}, []
    champ_sc = (current.scorecard if current else {}) or {}
    for k in GATE_KEYS:
        c = candidate.scorecard.get(k)
        ch = champ_sc.get(k)
        if c is None:
            continue
        if ch is not None:
            deltas[k] = round(c - ch, 3)
            if c < ch:                              # 任一指标退步 → 拦截
                blocked.append(k)
    if blocked:
        raise HTTPException(409, f"晋升被拦截：以下指标低于现任 production {blocked}；delta={deltas}")

    # ── 通过：旧 production 降 staged，候选升 production ──
    if current and current.id != candidate.id:
        current.status = "staged"
    candidate.status = "production"
    write_audit(db, admin, "promote_prompt", "prompt_version", candidate.id, {
        "from": current.name if current else None, "to": candidate.name, "eval_delta": deltas,
    })
    await db.commit()
    await db.refresh(candidate)
    return candidate


@router.post("/prompts/{name}/rollback", response_model=PromptVersionOut)
async def rollback_prompt(
    name: str,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """一键把 production 拨到指定(通常是上一个绿色)版本——回滚不走 eval-gate(救火优先)。"""
    target = await db.scalar(select(PromptVersion).where(PromptVersion.name == name))
    if target is None:
        raise HTTPException(404, "版本不存在")
    current = await db.scalar(select(PromptVersion).where(PromptVersion.status == "production"))
    if current and current.id != target.id:
        current.status = "staged"
    target.status = "production"
    write_audit(db, admin, "rollback_prompt", "prompt_version", target.id, {
        "from": current.name if current else None, "to": target.name,
    })
    await db.commit()
    await db.refresh(target)
    return target


# ── 模型路由：查看 / 更新 champion/challenger/canary ──
@router.get("/model-routing", response_model=ModelRoutingOut)
async def get_routing(db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(ModelRouting).where(ModelRouting.task == "soap"))
    if row is None:                                 # 没配过 → 返回默认(不写库)
        return ModelRoutingOut(task="soap", champion="openai", challenger=None, canary_pct=0)
    return row


@router.put("/model-routing", response_model=ModelRoutingOut)
async def update_routing(
    body: ModelRoutingUpdate,
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not (0 <= body.canary_pct <= 100):
        raise HTTPException(400, "canary_pct 必须在 0~100")
    row = await db.scalar(select(ModelRouting).where(ModelRouting.task == "soap"))
    if row is None:
        row = ModelRouting(task="soap")
        db.add(row)
    row.champion, row.challenger, row.canary_pct = body.champion, body.challenger, body.canary_pct
    write_audit(db, admin, "update_routing", "model_routing", row.id, {
        "champion": row.champion, "challenger": row.challenger, "canary_pct": row.canary_pct,
    })
    await db.commit()
    await db.refresh(row)
    return row


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
   
    
@router.post("/tenants")
async def provision_tenant(
    body: dict,                                  # {"slug","name","admin_email","admin_password"}
    admin: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    t = Tenant(slug=body["slug"], name=body["name"])
    db.add(t); await db.flush()                  # 拿到 t.id
    # 给新租户建一个管理员账号(密码哈希复用 security)
    from app.core.security import hash_password
    db.add(User(email=body["admin_email"].lower(), password_hash=hash_password(body["admin_password"]),
                role="admin", first_name="Clinic", last_name="Admin", tenant_id=t.id))
    # seed 几个默认模板到该租户(让新诊所开箱即用)
    db.add(Template(name="General SOAP", encounter_type="general",
                    system_prompt="You are an experienced clinical documentation specialist.",
                    tenant_id=t.id))
    write_audit(db, admin, "provision_tenant", "tenant", t.id, {"slug": t.slug})
    await db.commit()
    return {"id": str(t.id), "slug": t.slug}