# backend/app/api/agent.py
import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import service
from app.api.deps import get_current_user, get_owned_encounter
from app.core.db import get_db
from app.models.encounter import Encounter
from app.models.user import User
from app.schemas.agent import ApproveBody, StartRunBody
from fastapi import Request, Response
from slowapi.util import get_remote_address
from app.core.ratelimit import limiter
from app.core.config import settings


router = APIRouter(prefix="/api/agent", tags=["agent"])


def _sse(events):
    async def gen():
        async for ev in events:
            yield f"data: {json.dumps(ev)}\n\n"
        yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


# ── 开跑：为某次就诊启动一次 chart-review ──────────────────────────────────────
@router.post("/encounters/{encounter_id}/runs")
@limiter.limit(settings.rate_limit_agent)
async def start_run(
    request: Request,
    response: Response,
    body: StartRunBody,
    encounter: Encounter = Depends(get_owned_encounter),   # 复用：校验这次就诊属于当前医生
    db: AsyncSession = Depends(get_db),
):
    run_id = str(uuid.uuid4())                              # 也是 checkpointer 的 thread_id
    # 是否有既往史(决定 planner 走不走取史分支)
    from app.api.encounters import _history_count
    has_history = (await _history_count(db, encounter.patient_id, encounter.id)) > 0
    initial = {
        "encounter_id": str(encounter.id),
        "provider_id": str(encounter.provider_id),
        "patient_id": str(encounter.patient_id),
        "transcript": body.transcript,
        "has_history": has_history,
    }
    # 先把 run_id 发给前端(它后续用 run_id 调 /approve)，再推进度
    async def events():
        yield {"type": "run_started", "run_id": run_id}
        async for ev in service.start_run(run_id, initial):
            yield ev
    return _sse(events())


# ── 审批后恢复：医生点完"通过/驳回"，用 run_id 把暂停的运行接着跑完 ──────────────────
@router.post("/runs/{run_id}/approve")
async def approve_run(
    run_id: str,
    body: ApproveBody,
    _user: User = Depends(get_current_user),
):
    # body.approved 是医生勾选保留的低置信编码列表
    return _sse(service.resume_run(run_id, {"approved": body.approved}))