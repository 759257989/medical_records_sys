# backend/app/agent/checkpointer.py
#
# ═══════════════════════════════════════════════════════════════════════════════
# 这个文件解决一个核心问题：
#   LangGraph 的 agent 执行过程可能被"打断"（比如等医生审批 ICD 编码），
#   打断后 HTTP 请求结束了，但 agent 的中间状态不能丢。
#   下次医生点"确认"时，必须能从断点继续，而不是从头跑一遍。
#
# 解决方案：Checkpointer（检查点）
#   每执行完一个图节点，LangGraph 就自动把当前完整的 AgentState
#   序列化后存入 Postgres。恢复时从库里读回来，接着跑。
#   这就像游戏存档——随时可以"读档"接着玩。
#
# 调用方式：
#   - 应用启动时调一次 ensure_setup()，建好存档用的表（已存在则跳过）。
#   - 每次 run / resume agent 时用 open_checkpointer() 拿到 cp 对象，
#     传给 graph.ainvoke(..., checkpointer=cp)。
#
# 为什么用 psycopg3 而不是 asyncpg？
#   AsyncPostgresSaver 内部用的是 psycopg3（python 官方 Postgres 驱动），
#   而我们的 SQLAlchemy ORM 连接串带了 "+asyncpg"。两者连接串格式不同，
#   所以这里把 "+asyncpg" 去掉，得到 psycopg3 能识别的纯 postgresql:// 格式。
# ═══════════════════════════════════════════════════════════════════════════════
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

# postgresql+asyncpg://...  →  postgresql://...(psycopg3 用)
CHECKPOINTER_URI = settings.database_url.replace("+asyncpg", "")


@asynccontextmanager
async def open_checkpointer():
    """返回一个 AsyncPostgresSaver 实例，用完自动关闭连接。

    用法（在 API 路由里）：
        async with open_checkpointer() as cp:
            await graph.ainvoke(state, config, checkpointer=cp)

    连接关闭后状态依然在 Postgres 里——下次同一 thread_id 进来时可以读回来。
    """
    async with AsyncPostgresSaver.from_conn_string(CHECKPOINTER_URI) as cp:
        yield cp


async def ensure_setup() -> None:
    """在 Postgres 里建好 checkpointer 需要的三张表（幂等，已存在则跳过）。

    建的表：
        checkpoints       — 每个 checkpoint 的元数据（thread_id、时间戳等）
        checkpoint_blobs  — 序列化后的完整 AgentState 数据
        checkpoint_writes — 每个节点写入的增量变更

    应在 FastAPI lifespan 启动阶段调用一次：
        async def lifespan(app):
            await ensure_setup()
            yield
    """
    async with AsyncPostgresSaver.from_conn_string(CHECKPOINTER_URI) as cp:
        await cp.setup()