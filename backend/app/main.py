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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：engine 已在 import db.py 时建好（连接池就绪），这里无需额外动作
    yield
    # 关停时：优雅释放连接池
    await engine.dispose()


app = FastAPI(title="AI Clinical Scribe", lifespan=lifespan)
app.include_router(auth_router)    
app.include_router(encounters_router) 
app.include_router(templates_router)  
app.include_router(icd_router)
app.include_router(admin_router)



@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    # 真正跑一句 SQL，确认“应用 → 连接池 → 数据库”整条链路通
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}