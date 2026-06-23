# app/core/db.py
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from app.core.config import settings
from sqlalchemy import text

# Engine：进程内只创建一次（模块在 import 时执行），它内部维护一个连接池
engine = create_async_engine(
    settings.database_url,
    pool_size=10,        # 池里常驻最多 10 条连接
    max_overflow=5,      # 高峰可临时再开 5 条，过后回收
    pool_pre_ping=True,  # 借出前先 ping，自动丢弃已被 DB 断开的死连接
    pool_recycle=1800,   # 连接最多用 30 分钟就回收重建（防止被 DB/防火墙掐断）
    echo=False,          # True 可打印 SQL，调试时用
)

# Session 工厂：每个请求用它“借”一个会话
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# FastAPI 依赖：每个请求进来借一个会话，结束后自动归还到池
async def get_db():
    async with SessionLocal() as session:
        # ★坑2：连接来自池，可能残留上个请求的 app.tenant_id。开局先清零 → fail closed，
        #        随后 get_current_user 再设成本请求真正的租户。
        await session.execute(text("SELECT set_config('app.tenant_id', '', false)"))
        yield session