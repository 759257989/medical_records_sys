# app/main.py
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.auth import router as auth_router 
from app.core.db import engine, get_db
from app.api.encounters import router as encounters_router   
from app.api.templates import router as templates_router     
from app.api.icd import router as icd_router
from app.api.admin import router as admin_router

from app.core.observability.tracing import flush as flush_traces
from app.agent.checkpointer import ensure_setup
from app.api import agent as agent_api

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
# app/main.py
from app.core.providers.circuit import all_breakers


from app.core.ratelimit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_setup()         # 一次性建好 langgraph 检查点表（幂等，已存在则跳过）
    yield
    # 关停时：优雅释放连接池
    flush_traces()              # ← 先把 trace 刷出去
    await engine.dispose()      # 再优雅释放连接池


app = FastAPI(title="AI Clinical Scribe", lifespan=lifespan)

# ① 把 limiter 挂到 app.state(slowapi 约定的位置)
app.state.limiter = limiter
# ② 超限时返回标准 429(而不是 500)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# ③ 中间件：让被装饰的端点生效 + 统一处理(也可只用装饰器，但加中间件更稳)
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth_router)
app.include_router(encounters_router)
app.include_router(templates_router)
app.include_router(icd_router)
app.include_router(admin_router)
app.include_router(agent_api.router)



@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    # 真正跑一句 SQL，确认“应用 → 连接池 → 数据库”整条链路通
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}

@app.get("/api/health/providers")
async def provider_health():
    return {
        name: {"state": b.state, "failures": b.failures}
        for name, b in all_breakers().items()
    }