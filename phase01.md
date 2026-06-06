# Phase 0 + 1 跟做手册 — 本地地基、脚手架、鉴权与数据模型

> 配套：[`function_list.md`](function_list.md)、[`DEVELOPMENT_GUIDE.md`](DEVELOPMENT_GUIDE.md)
> 本篇范围：**本地把整套骨架跑通**（不碰 AWS，AWS 部署放后续单独文档）。
> 跟做策略：**本地先跑通**。我们用 Docker 起一个带 pgvector 的 Postgres，搭好 FastAPI 后端 + React 前端骨架，做好连接池、数据库迁移、鉴权和数据模型。AWS 上线在后面的文档里把「本地密钥」换成「Secrets Manager」、把「本地 DB」换成「RDS」即可——**架构现在就为可替换设计好**。

## 跟完本篇你会得到什么

- 一个本地可运行的 PostgreSQL（含 `pgvector` 扩展），数据用 Docker 卷持久化。
- 一个 FastAPI 后端，带：**应用级连接池**、健康检查、Alembic 迁移、**完整的归一化数据库 schema**。
- 4 个种子账号（3 provider + 1 admin）+ 几个笔记模板。
- 真实的登录系统：bcrypt 密码哈希 + JWT + 角色（provider/admin）+ 数据隔离 + 停用即失效。
- 一个 React 前端：登录页 + 受保护路由 + 自动带 token + 401 自动登出，刷新后自动恢复登录态。

---

## 0. 前置条件

先确认这几样装好了（终端逐条执行，能打印版本即可）：

```bash
python3 --version     # 需要 3.11+
node --version        # 需要 18+
docker --version      # 用来跑本地 Postgres
```

> 没有 Docker 也行：可本地装 Postgres 16 + pgvector，但 Docker 最省事、最不容易出环境问题，强烈推荐。

---

## 目录结构总览（跟做完后的样子）

```
kyron_med/
├── docker-compose.yml          # 本地 Postgres + pgvector
├── function_list.md
├── DEVELOPMENT_GUIDE.md
├── phase01.md                  # 本文档
├── backend/
│   ├── .env                    # 本地密钥（不入库）
│   ├── .env.example            # 示例（入库）
│   ├── .gitignore
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/0001_initial.py
│   └── app/
│       ├── __init__.py
│       ├── main.py             # 应用入口 + 健康检查
│       ├── seed.py             # 种子账号
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py       # 配置（本地 env，AWS 可替换）
│       │   ├── db.py           # 连接池 + 会话
│       │   └── security.py     # 密码哈希 + JWT
│       ├── models/             # SQLAlchemy 数据模型（每张表一个文件）
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── user.py
│       │   ├── patient.py
│       │   ├── template.py
│       │   ├── encounter.py
│       │   ├── note.py
│       │   ├── icd.py
│       │   └── audit.py
│       ├── schemas/            # Pydantic 出入参模型
│       │   ├── __init__.py
│       │   └── auth.py
│       └── api/
│           ├── __init__.py
│           ├── deps.py         # 鉴权依赖（当前用户 / 管理员 / 归属校验）
│           └── auth.py         # 登录接口
└── frontend/                   # Vite + React + TS
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── index.css
        ├── api/client.ts
        ├── auth/AuthContext.tsx
        ├── components/ProtectedRoute.tsx
        └── pages/{LoginPage,DashboardPage}.tsx
```

---

# Part A · Phase 0：本地地基 + 脚手架

## A1. 启动本地数据库（Docker + pgvector）

在项目根目录 `kyron_med/` 创建 `docker-compose.yml`：

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16        # 官方 Postgres 16 镜像，已内置 pgvector 扩展
    container_name: scribe_db
    environment:
      POSTGRES_USER: scribe
      POSTGRES_PASSWORD: scribe_local_pw
      POSTGRES_DB: scribe
    ports:
      - "5432:5432"                       # 把容器 5432 映射到本机 5432
    volumes:
      - pgdata:/var/lib/postgresql/data   # 数据持久化，容器删了数据还在

volumes:
  pgdata:
```

启动并确认：

```bash
docker compose up -d          # 后台启动
docker compose ps             # 看到 scribe_db 状态 Up 即可
```

🔍 **这段在做什么**：用一行配置起一个生产同款的 Postgres 16，且镜像自带 `pgvector`（后面 ICD-10 向量检索要用）。`volumes` 让数据落在命名卷里——你重启电脑、删容器,数据都还在,符合「持久数据不能用内存/临时存储」的要求。本地用固定密码没关系,因为它只监听你本机；上线时会换成 RDS + Secrets Manager。

---

## A2. 后端骨架与依赖

```bash
mkdir -p backend/app/{core,models,schemas,api}
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

创建 `backend/requirements.txt`：

```text
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
psycopg[binary]>=3.1
alembic>=1.13
pydantic>=2.7
pydantic-settings>=2.3
email-validator>=2.1
pyjwt>=2.8
bcrypt>=4.1
openai>=1.40
pgvector>=0.3
boto3>=1.34
```

安装：

```bash
pip install -r requirements.txt
```

🔍 **每个依赖干嘛的**：
- `fastapi` + `uvicorn`：Web 框架 + ASGI 服务器。
- `sqlalchemy[asyncio]` + `asyncpg`：ORM + 异步 Postgres 驱动（**应用运行时**用它，配合连接池）。
- `psycopg[binary]`：**仅 Alembic 迁移时**用的同步驱动（迁移用同步更简单稳）。两套驱动各司其职。
- `alembic`：数据库迁移（建表/改表的版本管理）。
- `pydantic` + `pydantic-settings`：数据校验 + 读配置。`email-validator` 让 `EmailStr` 生效。
- `pyjwt`：签发/校验 JWT。`bcrypt`：密码哈希。
- `openai` / `pgvector`：后续 Phase 用（生成 / 向量检索），现在先装上。
- `boto3`：后续 AWS Secrets Manager 用。

接着创建各包的 `__init__.py`（让 Python 把目录当成包）：

```bash
touch app/__init__.py app/core/__init__.py app/models/__init__.py app/schemas/__init__.py app/api/__init__.py
```

---

## A3. 配置与密钥抽象（`config.py`）

创建 `backend/app/core/config.py`：

```python
# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 从 backend/.env 读取；环境变量名大小写不敏感（database_url ⇄ DATABASE_URL）
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 运行时用 asyncpg 驱动连接（异步）
    database_url: str = "postgresql+asyncpg://scribe:scribe_local_pw@localhost:5432/scribe"

    jwt_secret: str = "dev-only-change-me"   # 上线务必换成长随机串
    jwt_expire_hours: int = 8

    openai_api_key: str = ""                 # 后续 Phase 用
    environment: str = "local"               # local / aws


settings = Settings()
```

🔍 **这段在做什么**：`Settings` 是「全应用唯一配置入口」。本地它从 `backend/.env` 读值；将来上 AWS 时，我们只需在启动前用 Secrets Manager 把值塞进环境变量（或加一个分支覆盖这些字段），**业务代码完全不用改**——这就是「为可替换设计」。所有密钥都从这里走，杜绝散落在代码里的硬编码。

创建 `backend/.env`（本地真实值，**不入库**）：

```text
# backend/.env
DATABASE_URL=postgresql+asyncpg://scribe:scribe_local_pw@localhost:5432/scribe
JWT_SECRET=please-change-this-to-a-long-random-string-0123456789
JWT_EXPIRE_HOURS=8
OPENAI_API_KEY=
ENVIRONMENT=local
```

创建 `backend/.env.example`（给别人看的模板，**入库**，不放真实值）：

```text
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://scribe:scribe_local_pw@localhost:5432/scribe
JWT_SECRET=
JWT_EXPIRE_HOURS=8
OPENAI_API_KEY=
ENVIRONMENT=local
```

创建 `backend/.gitignore`：

```text
# backend/.gitignore
.env
venv/
__pycache__/
*.pyc
```

🔍 **为什么分 `.env` 和 `.env.example`**：需求明确「仓库里不能有明文密钥，包括 `.env`」。所以 `.env` 进 `.gitignore`（本地用），只把不含秘密的 `.env.example` 提交,让协作者知道需要哪些变量。

---

## A4. 数据库连接池（`db.py`）⭐ 重点

创建 `backend/app/core/db.py`：

```python
# app/core/db.py
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from app.core.config import settings

# ① Engine：进程内只创建一次（模块在 import 时执行），它内部维护一个连接池
engine = create_async_engine(
    settings.database_url,
    pool_size=10,        # 池里常驻最多 10 条连接
    max_overflow=5,      # 高峰可临时再开 5 条，过后回收
    pool_pre_ping=True,  # 借出前先 ping，自动丢弃已被 DB 断开的死连接
    pool_recycle=1800,   # 连接最多用 30 分钟就回收重建（防止被 DB/防火墙掐断）
    echo=False,          # True 可打印 SQL，调试时用
)

# ② Session 工厂：每个请求用它“借”一个会话
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ③ FastAPI 依赖：每个请求进来借一个会话，结束后自动归还到池
async def get_db():
    async with SessionLocal() as session:
        yield session
```

🔍 **这段在做什么（务必理解，评审必问）**：
- **连接池的本质**：建立一条 DB 连接很贵（TCP + 认证）。`engine` 在应用启动时建好一个「连接池」（一组已经连好的连接），之后每个请求**从池里借**一条用完**还回去**，而不是每次新建。这正是需求里「EC2 不得每请求新开连接」的实现。
- `pool_size=10 / max_overflow=5`：常驻 10 条，突发再借 5 条，上限 15。够小型应用用。
- `pool_pre_ping=True`：RDS/网络偶尔会悄悄断连，借出前先探活，避免把「死连接」给请求导致报错。
- `get_db()` 是 FastAPI 的「依赖」：写 `db = Depends(get_db)` 的接口，进来自动拿一条会话，函数返回后 `async with` 自动 commit/rollback/归还。**你永远不用手动开关连接。**

---

## A5. 应用入口 + 健康检查（`main.py`）

创建 `backend/app/main.py`：

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：engine 已在 import db.py 时建好（连接池就绪），这里无需额外动作
    yield
    # 关停时：优雅释放连接池
    await engine.dispose()


app = FastAPI(title="AI Clinical Scribe", lifespan=lifespan)


@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    # 真正跑一句 SQL，确认“应用 → 连接池 → 数据库”整条链路通
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
```

🔍 **这段在做什么**：`lifespan` 管「应用启动/关停」的生命周期；关停时 `engine.dispose()` 把池里的连接干净关掉。`/api/health` 不只是返回 `ok`,而是**真的去查一次库**,所以它一旦通,说明配置、驱动、连接池、数据库全都对。所有接口路径统一前缀 `/api`,方便 nginx 把 `/api` 转发给后端、其余路径给前端。

---

## A6. 跑起来验证（Phase 0 后端 DoD）

在 `backend/`、虚拟环境激活、Docker 的 DB 在跑的前提下：

```bash
uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```bash
curl -s http://localhost:8000/api/health
# 预期输出： {"status":"ok","db":"ok"}
```

也可浏览器打开 `http://localhost:8000/docs` 看到自动生成的 API 文档。

✅ 看到 `{"status":"ok","db":"ok"}` 说明：FastAPI 起来了、连接池连上了本地 Postgres。Phase 0 后端地基完成。

> 排错：`db` 不是 ok → 多半是 Docker 的 DB 没起（`docker compose ps`）或 `.env` 里 `DATABASE_URL` 写错。

---

## A7. 前端脚手架（Vite + React + TS）

回到项目根目录 `kyron_med/`：

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install axios react-router-dom
```

配置开发代理 `frontend/vite.config.ts`：

```ts
// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 前端 dev 跑在 5173，把 /api 开头的请求转发给后端 8000
      "/api": "http://localhost:8000",
    },
  },
});
```

🔍 **这段在做什么**：`npm create vite` 生成一个 React+TS 工程。关键是 `server.proxy`：开发时前端在 `:5173`、后端在 `:8000`,直接跨端口请求会有跨域（CORS）问题。配了代理后,前端调 `/api/...` 会被 Vite 透明转发到 `:8000`,**等于同源**,不用写 CORS。这也精确模拟了上线后 nginx 的角色（nginx 把 `/api` 转给后端）——本地和线上行为一致。

先确认前端能跑：

```bash
npm run dev
# 浏览器打开它给出的 http://localhost:5173/ ，看到 Vite 默认页即可
```

✅ Phase 0 完成：本地数据库、后端（含连接池/健康检查）、前端骨架都跑起来了。

---

# Part B · Phase 1：鉴权 + 数据模型

## B1. 定义数据模型（SQLAlchemy Models）

模型即「Python 类 ↔ 数据库表」的映射。先建基类。

`backend/app/models/base.py`：

```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有模型的基类；Base.metadata 汇总了全部表结构，供 Alembic 使用。"""
    pass
```

`backend/app/models/user.py`：

```python
# app/models/user.py
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    # provider 与 admin 同表，靠 role 区分；CHECK 约束防止写入非法角色
    __table_args__ = (CheckConstraint("role IN ('provider','admin')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

🔍 **这段在做什么**：定义 `users` 表。要点：①`id` 用 UUID,Python 侧 `default=uuid.uuid4` 自动生成,不依赖数据库扩展；②**只存 `password_hash` 不存明文密码**；③`role` 用 CHECK 约束兜底；④`is_active` 是「停用」开关（Admin 停用 provider 用）；⑤`created_at` 用数据库的 `now()` 自动填。

`backend/app/models/patient.py`：

```python
# app/models/patient.py
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 注意：按 (lower(first), lower(last), dob) 去重的“自然键”唯一索引在迁移里建（函数索引）
```

🔍 **为什么这样**：需求要「按 名+姓+出生日期 匹配复诊患者」。我们会在迁移里建一个**大小写不敏感的唯一索引**,保证同一个人不会被重复建档,且复诊时能精确命中既往档案。

`backend/app/models/template.py`：

```python
# app/models/template.py
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    encounter_type: Mapped[str | None] = mapped_column(String(100))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)  # 注入 AI 的指令体
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

🔍 **为什么有 `is_deleted` 软删除**：encounter 会引用模板,直接物理删除会让历史记录「断链」。软删除（标记为已删但不真删）既能让 Admin「删除」模板,又保住审计可追溯。`system_prompt` 是模板的灵魂——不同模板靠它让 AI 输出不同风格。

`backend/app/models/encounter.py`：

```python
# app/models/encounter.py
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (
        CheckConstraint("status IN ('draft','generated','finalized')", name="ck_enc_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"), nullable=False)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    transcript: Mapped[str | None] = mapped_column(Text)          # 原始转录/观察
    working_note: Mapped[dict | None] = mapped_column(JSONB)      # 未保存的在编草稿(S/O/A/P)，autosave 到这
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

🔍 **为什么草稿放这里**：`encounter` 同时承担「就诊记录」和「在编草稿」。`transcript` 存输入,`working_note`（JSONB）存尚未正式保存的 SOAP 草稿。这样 Phase 3 的「刷新/换设备恢复草稿」几乎免费——草稿本就在服务端。`status` 区分 草稿/已生成/已定稿。

`backend/app/models/note.py`（版本表 + 版本-ICD 关联表）：

```python
# app/models/note.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NoteVersion(Base):
    __tablename__ = "note_versions"
    # 同一 encounter 下版本号唯一 —— 从数据库层面保证“追加式、永不覆盖”
    __table_args__ = (UniqueConstraint("encounter_id", "version_no", name="uq_note_enc_ver"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    subjective: Mapped[str | None] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text)
    assessment: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # 谁保存的
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # 何时


class NoteVersionCode(Base):
    __tablename__ = "note_version_codes"

    note_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("note_versions.id"), primary_key=True)
    icd10_code_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("icd10_codes.id"), primary_key=True)
```

🔍 **为什么这样设计版本**：每次保存写一条**新**`NoteVersion`（version_no 自增）,`UniqueConstraint(encounter_id, version_no)` 让「旧版本被覆盖」在数据库层面就不可能发生——这是审计要求的硬保证。`created_by`+`created_at` 记录「谁、何时」。ICD 码不塞进 `assessment` 文本里,而是用关联表 `note_version_codes` 规范化关联到受控码表（归一化正确做法）。

`backend/app/models/icd.py`：

```python
# app/models/icd.py
import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base


class Icd10Code(Base):
    __tablename__ = "icd10_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))  # 语义向量，Phase 3 填充
```

🔍 **为什么现在就建**：数据模型阶段要把 schema 一次建全。`embedding` 用 pgvector 的 `Vector(1536)` 类型（对应 OpenAI `text-embedding-3-small` 维度）,现在留空,Phase 3 做 ICD-10 检索时灌入向量。

`backend/app/models/audit.py`：

```python
# app/models/audit.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)        # 如 deactivate_provider
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

🔍 **为什么有这张表**：记录管理类敏感操作（停用账号、改模板等）。注意字段叫 `details` 而不是 `metadata`——因为 `metadata` 是 SQLAlchemy 的保留属性名,会冲突。

最后让所有模型「被加载」（Alembic 自动生成迁移时要能看到它们）。编辑 `backend/app/models/__init__.py`：

```python
# app/models/__init__.py
from app.models.base import Base
from app.models.user import User
from app.models.patient import Patient
from app.models.template import Template
from app.models.encounter import Encounter
from app.models.note import NoteVersion, NoteVersionCode
from app.models.icd import Icd10Code
from app.models.audit import AuditLog

__all__ = [
    "Base", "User", "Patient", "Template", "Encounter",
    "NoteVersion", "NoteVersionCode", "Icd10Code", "AuditLog",
]
```

---

## B2. Alembic 迁移：建表

初始化 Alembic（在 `backend/` 下）：

```bash
alembic init alembic
```

它生成了 `alembic.ini` 和 `alembic/` 目录。我们要让 Alembic：①用我们 `settings` 里的连接串（但换成**同步**驱动 psycopg）；②认识我们的所有模型。

**完整替换** `backend/alembic/env.py` 为：

```python
# backend/alembic/env.py
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 能 import 到 app 包（从 backend/ 运行）
sys.path.append(os.getcwd())

from app.core.config import settings           # noqa: E402
from app.models import Base                     # noqa: E402  (导入即注册了全部表)

config = context.config

# Alembic 用同步驱动跑迁移：把运行时的 +asyncpg 换成 +psycopg
config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("+asyncpg", "+psycopg"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

🔍 **这段在做什么**：`env.py` 是 Alembic 的入口。三个关键点：①`sys.path.append` 让它能找到 `app`；②把连接串里的 `asyncpg` 换成 `psycopg`——迁移用同步驱动更省心；③`target_metadata = Base.metadata` 让 Alembic 知道「应该有哪些表」。

下面**手写**首个迁移（比自动生成更可控，尤其要先建 `vector` 扩展、再建带向量列的表，顺序很重要）。

先生成一个空迁移文件：

```bash
alembic revision -m "initial schema"
```

它会在 `alembic/versions/` 下生成一个 `xxxx_initial_schema.py`。把它的内容**整体替换**为下面（文件名前缀保持它自己生成的即可）：

```python
# alembic/versions/xxxx_initial_schema.py
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001_initial"          # 若与文件名不一致，改成文件里已有的 revision 值
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) 先装 pgvector 扩展（建带向量列的表之前必须先有它）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1) users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('provider','admin')", name="ck_users_role"),
    )

    # 2) patients（+ 大小写不敏感的自然键唯一索引）
    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_patients_identity "
        "ON patients (lower(first_name), lower(last_name), dob)"
    )

    # 3) templates
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("encounter_type", sa.String(100)),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 4) icd10_codes（带向量列）
    op.create_table(
        "icd10_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536)),
    )
    # 余弦相似度的近似最近邻索引（300 行其实不需要，但展示工程意识）
    op.execute("CREATE INDEX ix_icd_vec ON icd10_codes USING hnsw (embedding vector_cosine_ops)")

    # 5) encounters
    op.create_table(
        "encounters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("transcript", sa.Text),
        sa.Column("working_note", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft','generated','finalized')", name="ck_enc_status"),
    )
    op.create_index("ix_enc_provider", "encounters", ["provider_id", "created_at"])
    op.create_index("ix_enc_patient", "encounters", ["patient_id"])

    # 6) note_versions
    op.create_table(
        "note_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("subjective", sa.Text),
        sa.Column("objective", sa.Text),
        sa.Column("assessment", sa.Text),
        sa.Column("plan", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("encounter_id", "version_no", name="uq_note_enc_ver"),
    )

    # 7) note_version_codes（多对多关联）
    op.create_table(
        "note_version_codes",
        sa.Column("note_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("note_versions.id"), primary_key=True),
        sa.Column("icd10_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("icd10_codes.id"), primary_key=True),
    )

    # 8) audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50)),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("details", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("note_version_codes")
    op.drop_table("note_versions")
    op.drop_index("ix_enc_patient", table_name="encounters")
    op.drop_index("ix_enc_provider", table_name="encounters")
    op.drop_table("encounters")
    op.execute("DROP INDEX IF EXISTS ix_icd_vec")
    op.drop_table("icd10_codes")
    op.drop_table("templates")
    op.execute("DROP INDEX IF EXISTS uq_patients_identity")
    op.drop_table("patients")
    op.drop_table("users")
```

执行迁移：

```bash
alembic upgrade head
```

🔍 **这段在做什么**：`upgrade()` 按依赖顺序建表——先装 `vector` 扩展,再建被引用的表（users/patients/templates/icd10_codes）,最后建引用它们的表（encounters/note_versions/...）。两个 `op.execute` 处理 Alembic 自动生成搞不定的东西：**函数唯一索引**（患者大小写不敏感去重）和 **hnsw 向量索引**。`downgrade()` 按相反顺序拆,保证 `alembic downgrade base && alembic upgrade head` 能干净重建全库（需求里的可重建性）。

验证表都建好了：

```bash
docker exec -it scribe_db psql -U scribe -d scribe -c "\dt"
# 应列出 users / patients / templates / encounters / note_versions /
#        note_version_codes / icd10_codes / audit_log
```

---

## B3. 密码哈希 + JWT（`security.py`）

创建 `backend/app/core/security.py`：

```python
# app/core/security.py
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    """把明文密码哈希成可存库的字符串。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配库里的哈希。"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user) -> str:
    """为用户签发一个有时效的 JWT。"""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user.id),   # subject = 用户 id
        "role": user.role,     # 角色，便于前端/中间件快速判断
        "exp": expire,         # 过期时间（PyJWT 会自动校验）
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
```

🔍 **这段在做什么**：
- `bcrypt` 是**单向**哈希且自带「盐」（gensalt）——即使数据库泄露,也无法反推出原始密码。验证时用 `checkpw` 比对,而不是去解密。
- `create_access_token` 生成 JWT：它是一段「用服务器密钥签名」的 token,里面装了 `sub`（用户 id）、`role`、`exp`（过期时间）。客户端拿着它访问接口,服务器用同一密钥验签即可确认身份——**无需在服务端存 session**,天然适合水平扩展。`exp` 让 token 自动过期,这也是后面「会话过期」边界场景的基础。

---

## B4. 种子账号（`seed.py`）

创建 `backend/app/seed.py`：

```python
# app/seed.py
import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models.user import User
from app.models.template import Template

# (email, password, first_name, last_name)
PROVIDERS = [
    ("dr.smith@clinic.test", "Provider123!", "John", "Smith"),
    ("dr.jones@clinic.test", "Provider123!", "Mary", "Jones"),
    ("dr.lee@clinic.test", "Provider123!", "David", "Lee"),
]
ADMIN = ("admin@clinic.test", "Admin123!", "Alice", "Admin")

TEMPLATES = [
    ("General SOAP", "general",
     "You are an experienced clinical documentation specialist. Produce a concise, "
     "professional SOAP note from the transcript. Never fabricate facts not present."),
    ("Orthopedic Follow-up", "ortho_followup",
     "You are documenting an orthopedic follow-up visit. Emphasize range of motion, "
     "pain scores, imaging, and rehab progress in the Objective and Plan sections."),
    ("New Patient Evaluation", "new_patient",
     "You are documenting a comprehensive new patient evaluation. Include a thorough "
     "history of present illness, full review of systems, and a broad differential."),
]


async def main() -> None:
    async with SessionLocal() as db:
        # 1) 账号（已存在则跳过，可重复运行）
        rows = [(*ADMIN, "admin")] + [(*p, "provider") for p in PROVIDERS]
        for email, pw, first, last, role in rows:
            exists = await db.scalar(select(User).where(User.email == email))
            if exists:
                print(f"skip user {email}")
                continue
            db.add(User(
                email=email.lower(),
                password_hash=hash_password(pw),
                role=role,
                first_name=first,
                last_name=last,
            ))
        await db.commit()

        # 2) 取 admin 作为模板创建者
        admin = await db.scalar(select(User).where(User.email == ADMIN[0]))

        # 3) 模板（按 name 去重）
        for name, etype, prompt in TEMPLATES:
            exists = await db.scalar(select(Template).where(Template.name == name))
            if exists:
                print(f"skip template {name}")
                continue
            db.add(Template(
                name=name, encounter_type=etype,
                system_prompt=prompt, created_by=admin.id if admin else None,
            ))
        await db.commit()

    await engine.dispose()
    print("seed done.")


if __name__ == "__main__":
    asyncio.run(main())
```

运行：

```bash
python -m app.seed
# 输出 seed done. ；重复运行会打印 skip ... 不会重复插
```

🔍 **这段在做什么**：往库里写演示用的 4 个账号和 3 个模板。每条都**先查后插**,所以脚本可以反复运行不会插重。密码经 `hash_password` 哈希后才入库。模板的 `system_prompt` 各不相同——这正是 Phase 4「不同模板让 AI 输出可见地不同」的数据基础。

> 演示账号密码记一下：admin `admin@clinic.test / Admin123!`,provider 例如 `dr.smith@clinic.test / Provider123!`。

---

## B5. Pydantic 出入参模型（`schemas/auth.py`）

创建 `backend/app/schemas/auth.py`：

```python
# app/schemas/auth.py
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    # from_attributes 让它能直接从 ORM 对象（User 实例）转换
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
    first_name: str
    last_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
```

🔍 **这段在做什么**：Pydantic 模型定义「接口收什么、回什么」并自动校验。`LoginRequest` 确保登录请求带合法 email + 密码。`UserOut` 是**对外**的用户信息（注意：**绝不包含 `password_hash`**——只暴露安全字段）。`TokenResponse` 是登录成功的返回结构。

---

## B6. 鉴权依赖（`api/deps.py`）⭐ 重点

创建 `backend/app/api/deps.py`：

```python
# app/api/deps.py
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.user import User

# 只用它从请求头里抽取 "Authorization: Bearer <token>"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_token")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    # 关键：每次请求都查 is_active —— 账号被停用后 token 立即失效
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="inactive_or_invalid")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """只允许 admin 访问的接口加这个依赖。"""
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user
```

🔍 **这段在做什么（鉴权三层防线，评审重点）**：
1. **认证**：`get_current_user` 从请求头取 token → 用服务器密钥验签 → 过期抛 401、非法抛 401。
2. **停用即失效**：验签通过后**再查一次数据库的 `is_active`**。这是为什么 admin 停用某 provider 后,对方即使握着没过期的 token 也会立刻被拒——满足 AUTH-7。
3. **授权（角色）**：`require_admin` 是个小依赖,挂到接口上就只放行 admin（用于后面的管理接口）。

> 数据级隔离（provider 只能看自己的 encounter）会在 Phase 2 加一个 `get_owned_encounter` 依赖：取出 encounter 后比对 `provider_id == 当前用户`,不符就 403。这里先把「认证 + 角色」打好地基。

---

## B7. 登录接口（`api/auth.py`）

创建 `backend/app/api/auth.py`：

```python
# app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    # 注意：用户不存在和密码错误返回同样的错误，避免“撞库”探测出哪些邮箱存在
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account_inactive")

    token = create_access_token(user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    """前端用它在刷新后恢复登录态，并验证 token 是否还有效。"""
    return UserOut.model_validate(user)
```

🔍 **这段在做什么**：
- `/login`：按 email 查用户 → 校验密码 → 检查是否被停用 → 签发 token 返回。安全细节：**用户不存在和密码错误返回同一条错误**,防止攻击者枚举出系统里有哪些邮箱。
- `/me`：受 `get_current_user` 保护,返回当前登录用户。前端刷新页面后调它「我还登着吗？是谁？」——既恢复登录态又顺带验证 token 有效。

---

## B8. 接线进 `main.py` + curl 测试

编辑 `backend/app/main.py`,加上 auth 路由：

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import router as auth_router      # 新增
from app.core.db import engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="AI Clinical Scribe", lifespan=lifespan)
app.include_router(auth_router)                       # 新增


@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
```

重启后端（`uvicorn app.main:app --reload --port 8000`），测试：

```bash
# 1) 登录拿 token
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@clinic.test","password":"Admin123!"}'
# 预期：{"access_token":"eyJ...","token_type":"bearer","user":{...,"role":"admin"}}

# 2) 用 token 访问 /me（把 <TOKEN> 换成上一步的 access_token）
curl -s http://localhost:8000/api/auth/me -H "Authorization: Bearer <TOKEN>"
# 预期：返回该用户信息

# 3) 错误密码
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@clinic.test","password":"wrong"}'
# 预期：{"detail":"invalid_credentials"}（HTTP 401）

# 4) 无 token 访问受保护接口
curl -s http://localhost:8000/api/auth/me
# 预期：{"detail":"Not authenticated"}（HTTP 401）
```

✅ 四条都符合预期 → 后端鉴权完成。

---

## B9. 前端：登录页 + 受保护路由

API 客户端 `frontend/src/api/client.ts`：

```ts
// frontend/src/api/client.ts
import axios from "axios";

const api = axios.create({ baseURL: "/api" }); // 走 vite 代理 → 后端 8000

// 请求拦截器：每次自动带上 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 响应拦截器：遇到 401（过期/失效）自动清 token 并回登录页
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      if (location.pathname !== "/login") location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default api;
```

🔍 **这段在做什么**：封装一个 axios 实例。**请求拦截器**自动把 `localStorage` 里的 token 加到每个请求头——业务代码不用每次手动加。**响应拦截器**统一处理 401：一旦 token 过期/失效,自动登出并跳登录页。这是后面「会话过期不丢数据」边界场景的前端基础。

登录态上下文 `frontend/src/auth/AuthContext.tsx`：

```tsx
// frontend/src/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import api from "../api/client";

type User = { id: string; email: string; role: string; first_name: string; last_name: string };
type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const Ctx = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 首次加载：若本地有 token，调 /me 恢复登录态（顺便验证 token）
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { setLoading(false); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => localStorage.removeItem("token"))
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const r = await api.post("/auth/login", { email, password });
    localStorage.setItem("token", r.data.access_token);
    setUser(r.data.user);
  };

  const logout = () => { localStorage.removeItem("token"); setUser(null); };

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}
```

🔍 **这段在做什么**：用 React Context 把「当前用户 / 登录 / 登出」做成全局状态,任何组件 `useAuth()` 就能用。`useEffect` 在刷新后自动用 token 调 `/me` 恢复登录——所以刷新页面不会掉登录态。

受保护路由 `frontend/src/components/ProtectedRoute.tsx`：

```tsx
// frontend/src/components/ProtectedRoute.tsx
import { JSX } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
```

登录页 `frontend/src/pages/LoginPage.tsx`：

```tsx
// frontend/src/pages/LoginPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await login(email, password);
      nav("/");
    } catch {
      setError("邮箱或密码错误");
    }
  };

  return (
    <div className="center">
      <form onSubmit={submit} className="card">
        <h1>Clinical Scribe</h1>
        <input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error">{error}</p>}
        <button type="submit">登录</button>
      </form>
    </div>
  );
}
```

仪表盘占位 `frontend/src/pages/DashboardPage.tsx`：

```tsx
// frontend/src/pages/DashboardPage.tsx
import { useAuth } from "../auth/AuthContext";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  return (
    <div className="page">
      <header className="topbar">
        <strong>Clinical Scribe</strong>
        <span>{user?.first_name} {user?.last_name} · {user?.role}</span>
        <button onClick={logout}>退出</button>
      </header>
      <main className="content">
        <h2>欢迎，{user?.first_name} 医生</h2>
        <p>这里将是 Phase 2 的就诊工作区（转录输入 + 流式生成 SOAP）。</p>
        {user?.role === "admin" && <p>（你是管理员，Phase 4 会有管理后台入口。）</p>}
      </main>
    </div>
  );
}
```

路由 `frontend/src/App.tsx`：

```tsx
// frontend/src/App.tsx
import { Routes, Route } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
    </Routes>
  );
}
```

入口 `frontend/src/main.tsx`（替换 Vite 默认内容）：

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
```

一点基础样式 `frontend/src/index.css`（替换默认内容，保持克制的临床观感）：

```css
/* frontend/src/index.css */
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1f2937; background: #f8fafc; }
.center { min-height: 100vh; display: grid; place-items: center; }
.card { display: flex; flex-direction: column; gap: 12px; width: 320px; padding: 28px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.card h1 { font-size: 18px; margin: 0 0 6px; }
.card input { padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; }
.card button { padding: 10px; background: #1d4ed8; color: #fff; border: 0; border-radius: 6px; cursor: pointer; font-size: 14px; }
.error { color: #dc2626; font-size: 13px; margin: 0; }
.topbar { display: flex; align-items: center; gap: 16px; padding: 12px 20px; background: #fff; border-bottom: 1px solid #e2e8f0; }
.topbar span { margin-left: auto; color: #475569; font-size: 14px; }
.topbar button { padding: 6px 12px; border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; cursor: pointer; }
.content { padding: 24px; }
```

🔍 **前端整体怎么转起来的**：`main.tsx` 把 `App` 包在 `BrowserRouter`（路由）和 `AuthProvider`（登录态）里。访问 `/` 时 `ProtectedRoute` 先看有没有登录——没登录跳 `/login`,登录了显示仪表盘。登录成功后 token 存进 `localStorage`,axios 拦截器后续自动带上;刷新页面 `AuthContext` 用 token 调 `/me` 把人「认回来」。

启动前端并联调：

```bash
cd frontend && npm run dev
```

浏览器开 `http://localhost:5173/`：未登录会被导到 `/login` → 用 `admin@clinic.test / Admin123!` 登录 → 进入仪表盘看到姓名和角色 → 刷新页面仍在登录态 → 点退出回到登录页。

---

## ✅ Definition of Done（Phase 0+1 自检清单）

- [ ] `docker compose ps` 显示 `scribe_db` Up；数据用命名卷持久化。
- [ ] `curl /api/health` 返回 `{"status":"ok","db":"ok"}`（连接池连库成功）。
- [ ] `alembic upgrade head` 成功；`\dt` 看到 8 张表；`alembic downgrade base && alembic upgrade head` 可干净重建。
- [ ] `python -m app.seed` 成功；4 账号 + 3 模板入库,重复运行不重复插。
- [ ] curl 四连测通过：登录拿 token / `/me` 成功 / 错误密码 401 / 无 token 401。
- [ ] 前端：能登录、刷新保持登录、退出生效；未登录访问 `/` 被导向 `/login`。
- [ ] 仓库无明文密钥：`.env` 在 `.gitignore` 里,只有 `.env.example` 入库。
- [ ] 连接池：`engine` 全局只建一次（在 `db.py` 模块级）,接口经 `Depends(get_db)` 借还,**没有**每请求新建连接的代码。

---

## 常见坑

- **`/api/health` 的 db 不是 ok**：DB 没起（`docker compose up -d`）或 `.env` 的 `DATABASE_URL` 写错。
- **`alembic` 报找不到 `app` 模块**：必须在 `backend/` 目录下运行 alembic（`env.py` 里 `sys.path.append(os.getcwd())` 依赖此）。
- **迁移报 `type "vector" does not exist`**：迁移里 `CREATE EXTENSION vector` 必须在建 `icd10_codes` 之前（本文顺序已正确）；也确认用的是 `pgvector/pgvector` 镜像。
- **`bcrypt` 报错**：确保装的是独立 `bcrypt` 包（本文没用 passlib,避免其与新版 bcrypt 的兼容坑）。
- **前端调接口 404/跨域**：检查 `vite.config.ts` 的 `server.proxy` 是否配了 `/api`,且后端在 `:8000` 跑着。
- **`EmailStr` 报缺少 email-validator**：确认 `requirements.txt` 里有 `email-validator` 并已安装。

---

## 下一步（Phase 2 预告）

地基已成：本地数据库 + 连接池 + 全量 schema + 鉴权 + 前端登录壳。Phase 2 进入项目核心——**就诊工作区 + SSE 流式生成 SOAP**：
1. 新建/恢复 encounter，录入转录；
2. `POST /api/encounters/{id}/generate` 用 OpenAI 流式产出 SOAP，前端逐字渲染；
3. 行内编辑 → 保存,触发 `note_versions` 追加写第一版。

> AWS 上线（EC2 + RDS + nginx + TLS + Secrets Manager）会在单独文档里做：届时只需把 `config.py` 的取值来源从 `.env` 切到 Secrets Manager、把 `DATABASE_URL` 指向 RDS,**业务代码零改动**。
