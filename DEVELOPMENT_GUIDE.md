# AI Clinical Scribe Platform — 72h 开发流程指引（单人实战手册）

> 配套文档：[`function_list.md`](function_list.md)（功能清单 + 优先级 + 验收标准）
> 技术栈：**FastAPI · React(Vite/TS) · PostgreSQL+pgvector · OpenAI GPT-4o · AWS(EC2/RDS/nginx/Secrets Manager)**

---

## 0. 怎么用这份手册 + 三条总原则

这份手册按「地基 → 核心 → 增强 → 打磨」分 6 个 Phase，每个 Phase 都给：**目标产出 / 关键步骤(命令+代码骨架) / 设计考量 / tradeoff / Definition of Done / 常见坑**。按顺序做，不要跳。

三条贯穿始终的原则：

1. **Infra-first 垂直切片**。第一天先把「最难、最容易翻车」的基础设施跑通——HTTPS、RDS 私网、Secrets、连接池、nginx——用一个 hello-world 应用打通整条部署管线。评分明确说「基础设施扎实 > 功能全」。**先证明能上线，再堆功能。**
2. **本地开发，定期重部署**。Phase 0 之后回到本地用 docker-compose 起 Postgres 快速迭代，每个 Phase 末尾 `git push` + EC2 拉取重启。不要在 EC2 上写业务代码。
3. **Prioritization 是被打分的**。宁可少做一个 P2，也要让 P0 链路「对用户感觉完整」。任何时候时间告急，照 `function_list.md` 的优先级从下往上砍（见 §12）。

---

## 1. 总体架构与技术选型理由

### 1.1 架构图（文字版）

```
                    ┌──────────────────────────── AWS VPC ────────────────────────────┐
                    │                                                                  │
   Browser  ──HTTPS─┼─►  EC2 (public subnet)                  RDS PostgreSQL           │
  (React SPA)       │    ┌─────────────────────────┐         (private subnet)          │
                    │    │ nginx :443 (TLS 终止)    │         ┌──────────────────┐      │
                    │    │  ├─ / → React 静态包      │         │ pgvector 扩展      │      │
                    │    │  └─ /api → 127.0.0.1:8000│──5432──►│ SG: 仅放行 EC2-SG │      │
                    │    │ gunicorn+uvicorn (FastAPI)│         └──────────────────┘      │
                    │    │  └─ SQLAlchemy async pool │                                   │
                    │    │ IAM Role ─► Secrets Mgr   │         (publicly_accessible=NO)  │
                    │    └───────────┬──────────────┘                                   │
                    └────────────────┼──────────────────────────────────────────────────┘
                                     │ HTTPS
                                     ▼
                              OpenAI API (GPT-4o 生成 + embeddings)
```

数据流（生成一条 SOAP）：
```
React → POST /api/encounters/{id}/generate (SSE)
  → FastAPI 解析患者身份 + 读当前激活模板(实时查库)
  → 若患者有历史: 用 tool_choice 强制 GPT-4o 调 get_patient_history
        → 后端执行 DB 查询 → 把历史作为 tool result 回喂
  → GPT-4o stream=True 逐 token 产出 SOAP
  → FastAPI 把 token 包成 SSE event 转发
  → React 边收边渲染到对应 SOAP 段
保存时 → POST /api/encounters/{id}/notes → 追加写 note_versions(version_no+1)
```

### 1.2 选型逐项 tradeoff

| 决策 | 选择 | 理由 | 放弃了什么 / 风险 |
|------|------|------|-------------------|
| 后端 | **FastAPI** | 原生 async 适合「流式转发 + 等 OpenAI」的 I/O 密集；Pydantic 类型安全；`StreamingResponse` 写 SSE 简单；Python 生态对 OpenAI/embedding 最顺。 | 与前端两套语言；需自己接 SSE 与鉴权。用 OpenAPI 自动生成类型缓解。 |
| 前端 | **React + Vite + TS** | 临床 UI 需要密集表格/表单/实时流，React 生态成熟；Vite 构建快；TS 防错。 | 比 Next.js 多配一层路由/构建。换来部署简单（纯静态包交给 nginx）。 |
| 数据库 | **PostgreSQL + pgvector** | 一个库同时满足关系型（归一化 schema）+ 向量检索（ICD-10），少一个组件；RDS 原生支持。 | 不引专用向量库（Pinecone 等）。300 条规模 pgvector 绰绰有余。 |
| AI 生成 | **GPT-4o** | 流式 + function calling 极成熟、稳定、低延迟；临床文档质量高；JSON/格式遵循好。 | 成本/隐私需注意（演示数据用假患者）。模型层做了 provider 封装便于替换。 |
| ICD 检索 | **pgvector + 预算 embedding** | 启动时对码库做一次 `text-embedding-3-small`，查询只需 embed 一次 + SQL `<=>`；可在 schema 评审中展示向量能力，最「真实」可防御。 | 比纯 LLM 排序多一步建库。换来查询低延迟、低成本、可解释。 |
| 鉴权 | **JWT（短期）+ is_active 校验** | 无状态、易水平扩展；停用通过每请求查 `is_active` 即时生效。 | 不做完整 refresh-token 撤销表（见 §5 tradeoff）。短期 token + 黑名单可加固。 |
| 流式协议 | **SSE（非 WebSocket）** | 生成是单向 server→client 流，SSE 天然契合、HTTP 原生、nginx 易配、断线自动重连。 | 不要 WS 的双向能力（这里不需要）。 |

> **Walkthrough 一句话**：「I/O 密集 + 单向流 + 一库多用 + 工具调用成熟」是这套选型的主线。

---

## 2. 数据库设计（ERD + 建表 + 归一化论证）

### 2.1 ERD（文字版）

```
users (provider / admin)
  └─1:N─ encounters ─N:1─ patients
                  │   └─N:1─ templates (nullable, ON DELETE SET NULL)
                  └─1:N─ note_versions (append-only)
                              └─1:N─ note_version_codes ─N:1─ icd10_codes
audit_log ─N:1─ users        icd10_codes (含 embedding vector)
```

### 2.2 建表（核心 DDL，省略部分约束）

```sql
-- 扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- 用户（provider + admin 同表，靠 role 区分）
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('provider','admin')),
  first_name    TEXT NOT NULL,
  last_name     TEXT NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 患者（按 first+last+dob 自然键去重）
CREATE TABLE patients (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name  TEXT NOT NULL,
  last_name   TEXT NOT NULL,
  dob         DATE NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (lower(first_name), lower(last_name), dob)   -- 复诊匹配
);

-- 笔记模板（结构化 prompt）
CREATE TABLE templates (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  encounter_type TEXT,                 -- ortho follow-up / new patient / urgent care...
  system_prompt TEXT NOT NULL,         -- 注入 GPT-4o 的指令体
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,  -- 软删除，保审计链
  created_by    UUID REFERENCES users(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 就诊（草稿也活在这里）
CREATE TABLE encounters (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id   UUID NOT NULL REFERENCES patients(id),
  provider_id  UUID NOT NULL REFERENCES users(id),
  template_id  UUID REFERENCES templates(id) ON DELETE SET NULL,
  status       TEXT NOT NULL DEFAULT 'draft'
               CHECK (status IN ('draft','generated','finalized')),
  transcript   TEXT,                   -- 原始转录/观察
  working_note JSONB,                  -- 未保存的在编草稿(S/O/A/P)，autosave 到这
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_enc_provider ON encounters(provider_id, created_at DESC);
CREATE INDEX ix_enc_patient  ON encounters(patient_id);

-- 笔记版本（追加式，永不覆盖）
CREATE TABLE note_versions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  encounter_id UUID NOT NULL REFERENCES encounters(id),
  version_no   INT  NOT NULL,
  subjective   TEXT, objective TEXT, assessment TEXT, plan TEXT,
  created_by   UUID NOT NULL REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (encounter_id, version_no)
);

-- 版本内的 ICD 码（归一化，不把码塞在 assessment 文本里）
CREATE TABLE note_version_codes (
  note_version_id UUID NOT NULL REFERENCES note_versions(id),
  icd10_code_id   UUID NOT NULL REFERENCES icd10_codes(id),
  PRIMARY KEY (note_version_id, icd10_code_id)
);

-- ICD-10 参考表 + 向量
CREATE TABLE icd10_codes (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code        TEXT UNIQUE NOT NULL,
  description TEXT NOT NULL,
  embedding   VECTOR(1536)            -- text-embedding-3-small
);
CREATE INDEX ix_icd_vec ON icd10_codes USING hnsw (embedding vector_cosine_ops);

-- 管理操作审计
CREATE TABLE audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users(id),
  action      TEXT NOT NULL,          -- deactivate_provider / edit_template ...
  entity_type TEXT, entity_id UUID,
  metadata    JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.3 归一化与索引论证（评审会逐表问）

- **为什么 users 一张表带 role，而不是 providers/admins 两表？** 二者字段重叠 95%，role 是行为差异不是数据差异；单表 + CHECK 约束 + RBAC 中间件更简洁，避免跨表 UNION 查全局。
- **patients 自然键 `UNIQUE(lower(first), lower(last), dob)`**：满足「复诊按姓名+DOB 匹配」，大小写不敏感避免重复建患者。
- **note_versions 追加式 + `UNIQUE(encounter_id, version_no)`**：保证「旧版本永不覆盖」从数据库层面强制；查历史 `ORDER BY version_no`。
- **ICD 码独立成表 + 关系表 note_version_codes**：码是受控词表（reference data），不内联进 assessment 文本，可被多版本/多笔记复用，可加 embedding 做检索——这是归一化的典型正确做法。
- **草稿放 encounters.working_note(JSONB) 而非单独 drafts 表**：草稿是 encounter 的瞬时状态，1:1 关系，放同表减少 join；正式保存时才快照进 note_versions。
- **templates 软删除（is_deleted）**：encounter 历史引用了模板，硬删会断审计链；软删 + `ON DELETE SET NULL` 双保险。
- **索引**：encounter 按 provider 时间倒序（列表页）、patient（历史注入查询）；ICD 用 hnsw 余弦索引（即使 300 行不必需，也展示向量工程意识）。

---

## 3. 72 小时时间盒

| 时段 | Phase | 产出 |
|------|-------|------|
| 0–8h | **P0 基建地基** | AWS 网络/RDS/EC2/nginx/TLS/Secrets/连接池打通；hello-world 上线 HTTPS。 |
| 8–16h | **P1 Auth + 数据模型** | Alembic 全 schema + seed 账号；登录/JWT/RBAC；前端登录壳。 |
| 16–32h | **P2 核心 Scribe + 流式** ⭐ | encounter 工作区；SSE 流式 SOAP；行内编辑；保存→版本。**最重头。** |
| 32–44h | **P3 历史注入 + ICD-10 + 草稿** | function calling 注入历史；pgvector 检索控件；autosave 草稿恢复。 |
| 44–56h | **P4 Admin + 实时模板** | 全局视图/筛选；provider 增停；模板 CRUD + 实时生效。 |
| 56–64h | **P5 边界 + Pioneer** | 两个 non-happy-path；Diff View 加分。 |
| 64–72h | **P6 打磨 + 硬化 + 演示稿** | UI 收尾；基建复检；walkthrough 防御要点。 |

> 留 ~6h 总缓冲分散在各 Phase 末。重头是 16–32h，别让前面侵占它。

---

## 4. Phase 0 — 基础设施地基（0–8h）P0

**目标产出**：一个返回 `{"db":"ok"}` 的 hello-world FastAPI，跑在 EC2、由 nginx 经有效 HTTPS 证书代理、从 Secrets Manager 取 RDS 凭证、用连接池连私网 RDS。把最难的先证明。

### 4.1 AWS 网络与资源（顺序）

1. **VPC**：1 个 VPC，2 个公有子网 + 2 个私有子网（RDS 子网组要≥2 AZ）。
2. **RDS**：PostgreSQL 16，放私有子网组，**`Public access = No`**，新建安全组 `rds-sg`。
3. **EC2**：t3.small（Amazon Linux 2023）放公有子网，安全组 `ec2-sg`（入站仅 443、22 限你的 IP）。
4. **安全组连线**：`rds-sg` 入站规则 = 5432 来源设为 `ec2-sg`（按安全组引用，不是 IP）。这就是「RDS 仅 VPC 内可达」的核心证据。
5. **IAM Role**：给 EC2 绑定可读目标 secret 的 role（`secretsmanager:GetSecretValue`）。
6. **Secrets Manager**：建两条——`scribe/db`（host/port/user/pass/dbname）、`scribe/openai`（api_key）。
7. **域名 + TLS**：用你拥有 DNS 的域名（或 DuckDNS 免费域名）A 记录指向 EC2 公网 IP；certbot 申 Let's Encrypt 证书（DNS-01 或 HTTP-01）。**不要自签。**

### 4.2 连接池 + Secrets（代码骨架）

```python
# app/core/secrets.py  —— 启动时取一次，缓存
import json, boto3, functools

@functools.lru_cache
def get_secret(name: str) -> dict:
    client = boto3.client("secretsmanager")   # 凭 EC2 IAM Role，无明文密钥
    return json.loads(client.get_secret_value(SecretId=name)["SecretString"])
```

```python
# app/core/db.py  —— 连接池只建一次（关键 P0）
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.secrets import get_secret

s = get_secret("scribe/db")
DATABASE_URL = f"postgresql+asyncpg://{s['user']}:{s['pass']}@{s['host']}:{s['port']}/{s['dbname']}"

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10, max_overflow=5,      # 池上限
    pool_pre_ping=True,                # 防陈旧连接(RDS 断连)
    pool_recycle=1800,                 # 30min 回收
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():                    # FastAPI 依赖：每请求借/还，不新建连接
    async with SessionLocal() as session:
        yield session
```

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield                              # engine 已在 import 时建立(全局单例)
    await engine.dispose()            # 关停时优雅释放池

app = FastAPI(lifespan=lifespan)

@app.get("/api/health")
async def health(db = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"db": "ok"}
```

### 4.3 nginx 反代（SSE 友好）

```nginx
# /etc/nginx/conf.d/scribe.conf
server {
  listen 443 ssl;
  server_name your-domain.example;
  ssl_certificate     /etc/letsencrypt/live/your-domain.example/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/your-domain.example/privkey.pem;

  root /var/www/scribe;              # React 构建产物
  location / { try_files $uri /index.html; }   # SPA 路由回退

  location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;            # ★ SSE 必须关 buffering，否则不流式
    proxy_read_timeout 3600s;       # 长连接
  }
}
server { listen 80; server_name your-domain.example; return 301 https://$host$request_uri; }
```

```ini
# /etc/systemd/system/scribe.service  —— 进程守护
[Service]
ExecStart=/opt/scribe/venv/bin/gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8000
Restart=always
```

### 4.4 设计考量 / tradeoff
- **为什么先做基建**：基建是评分里最硬、最容易在 deadline 前翻车的部分（证书、安全组、IAM）。先打通管线，后面只是往里填业务。
- **EC2 放公有子网 + nginx 终止 TLS**：相比 ALB 更省钱省配置，满足「不直接暴露 app、有反代、有效证书」。tradeoff：少了 ALB 的弹性/WAF，但 72h demo 够用。
- **Secrets 启动取一次 + lru_cache**：避免每请求打 Secrets Manager（有费用/限流）。tradeoff：轮换 secret 需重启；演示无妨。

### 4.5 DoD
- [ ] `curl https://your-domain/api/health` → `{"db":"ok"}`，浏览器证书无警告。
- [ ] 从本机 `psql -h <rds-endpoint>` **连不上**（超时）；EC2 上能连上。
- [ ] `grep -ri "password\|api_key" 仓库` 无明文；`.env` 不入库（`.gitignore`）。
- [ ] EC2 上 `systemctl restart scribe` 后服务自起、数据在。

### 4.6 常见坑
- nginx 不关 `proxy_buffering` → SSE 变「一次性整段」，直接砸 GEN-3 评分。
- RDS 子网组少于 2 AZ → 创建失败。
- IAM Role 没附到 EC2 实例 → boto3 取 secret 403。
- 证书用了 staging endpoint → 浏览器仍报不受信；用 certbot 正式环境。

---

## 5. Phase 1 — Auth + 数据模型（8–16h）P1/P0

**目标产出**：全 schema 迁移上线；4 个种子账号；登录返回 JWT；RBAC 中间件；前端登录页 + 受保护路由壳。

### 5.1 关键步骤
1. 用 §2 DDL 写 SQLAlchemy 模型 + Alembic 迁移，`alembic upgrade head`。
2. Seed 脚本：3 provider + 1 admin（bcrypt 哈希）；几条 templates。
3. 登录 + JWT + 依赖式鉴权。

```python
# app/core/auth.py
from jose import jwt; from passlib.hash import bcrypt
from fastapi import Depends, HTTPException
ALGO="HS256"  # 密钥来自 Secrets Manager

def make_token(user): return jwt.encode(
    {"sub":str(user.id),"role":user.role,"exp":...}, SECRET, ALGO)

async def current_user(token=Depends(oauth2), db=Depends(get_db)):
    data = jwt.decode(token, SECRET, [ALGO])           # 过期→抛 401
    user = await db.get(User, data["sub"])
    if not user or not user.is_active:                 # ★ 停用即时失效(AUTH-7)
        raise HTTPException(401, "inactive_or_invalid")
    return user

def require_admin(u=Depends(current_user)):
    if u.role!="admin": raise HTTPException(403); return u
```

数据级隔离（AUTH-3）——provider 查 encounter 必带 `provider_id == current_user.id`：
```python
async def get_owned_encounter(eid, u=Depends(current_user), db=Depends(get_db)):
    enc = await db.get(Encounter, eid)
    if not enc or (u.role!="admin" and enc.provider_id!=u.id):
        raise HTTPException(403)
    return enc
```

### 5.2 设计考量 / tradeoff
- **JWT 无状态** vs **服务端 session**：JWT 易扩展、前端简单；代价是「主动撤销难」。本设计用「短期 token(如 8h) + 每请求查 `is_active`」覆盖停用/失效，无需 refresh 撤销表。若要更严，可加 token 版本号或黑名单表——**列为 §12 可砍/可加项**。
- **token 放哪**：演示用 `localStorage`（跨设备恢复草稿靠服务端，不靠 token）。生产更倾向 httpOnly cookie（防 XSS 窃取）——walkthrough 要能讲清这个 tradeoff。

### 5.3 DoD
- [ ] 4 账号能登录；provider 拿别人 encounter id → 403；admin → 200。
- [ ] 删掉/篡改 token → 401。
- [ ] `alembic downgrade base && upgrade head` 干净重建。

---

## 6. Phase 2 — 核心 Scribe + 流式（16–32h）⭐ P0

> 这是整个项目的心脏，分数权重最高。慢一点、做扎实。

**目标产出**：provider 新建 encounter → 输入转录 → 点 Generate → SSE 逐 token 流式渲染四段 SOAP（含语义 ICD）→ 行内编辑 → 保存 → 写 V1。

### 6.1 流式生成端点（SSE + 结构化）

约定让 GPT-4o 输出**带分隔标记**的流，便于前端归段。系统提示要求严格输出：
```
###SUBJECTIVE### ... ###OBJECTIVE### ... ###ASSESSMENT### ... ###ICD### code|desc ... ###PLAN### ...
```

```python
# app/api/generate.py
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
client = AsyncOpenAI(api_key=get_secret("scribe/openai")["api_key"])

@router.post("/encounters/{eid}/generate")
async def generate(eid, enc=Depends(get_owned_encounter), db=Depends(get_db)):
    template = await load_active_template(db, enc.template_id)   # ★ 实时查库(ADM-6)
    messages = build_messages(template.system_prompt, enc.transcript, enc.patient)

    async def event_stream():
        # ——（历史注入两段式见 §7，这里先讲纯生成）——
        stream = await client.chat.completions.create(
            model="gpt-4o", messages=messages, stream=True, temperature=0.2)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield f"data: {json.dumps({'t': delta})}\n\n"   # SSE 帧
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

前端用 `fetch` + ReadableStream（需带 Authorization 头，故不用原生 EventSource）：
```ts
const res = await fetch(`/api/encounters/${id}/generate`, {
  method: "POST", headers: { Authorization: `Bearer ${token}` }});
const reader = res.body!.getReader(); const dec = new TextDecoder();
let buf = "";
for (;;) {
  const { value, done } = await reader.read(); if (done) break;
  buf += dec.decode(value, { stream: true });
  for (const frame of buf.split("\n\n")) {        // 解析 SSE 帧
    if (!frame.startsWith("data:")) continue;
    const { t } = JSON.parse(frame.slice(5));
    if (t) appendToken(t);                          // 增量塞入 + 按 ###段### 归位
  }
}
```

### 6.2 Prompt 工程（GEN-6，要能讲）
- **System**：角色（资深临床文档专员）+ 严格输出格式（四段 + ###ICD### 行）+ 临床语气 + 「只依据转录与提供的历史，缺信息写 "Not documented"，禁止编造」。
- **模板注入**：把激活 template 的 `system_prompt` 拼到 system 段——这是「模板可见地改变输出」的机制（ADM-5）。
- **ICD 约束**：要求 Assessment 给出 ≥1 个 ICD-10 码，且必须与内容语义相关（后续可与 pgvector 检索结果交叉校验）。
- **temperature=0.2**：临床文档要稳定可复现，不要发散。

### 6.3 保存 → 追加版本（VER-1）
```python
@router.post("/encounters/{eid}/notes")
async def save_note(eid, body, enc=Depends(get_owned_encounter), u=..., db=...):
    nxt = (await db.scalar(select(func.max(NoteVersion.version_no))
                           .where(NoteVersion.encounter_id==eid)) or 0) + 1
    nv = NoteVersion(encounter_id=eid, version_no=nxt, created_by=u.id,
                     subjective=body.s, objective=body.o,
                     assessment=body.a, plan=body.p)
    db.add(nv); await db.flush()
    await link_codes(db, nv.id, body.icd_codes)     # 写 note_version_codes
    enc.status="finalized"; await db.commit()
    return {"version_no": nxt}
```

### 6.4 tradeoff
- **分隔标记 vs 结构化 JSON 流**：纯文本 + `###段###` 标记最易流式增量渲染（JSON 半截无法解析）。代价是解析靠约定，需 system prompt 强约束 + 容错。这是流式场景的常见正确取舍。
- **SSE 帧用 JSON 包 token**：避免 token 内含换行/`data:` 破坏帧格式。

### 6.5 DoD
- [ ] 文字**逐字出现**（非 spinner→整段），四段正确归位，Assessment 有 ICD。
- [ ] 改两个字再保存 → DB 出现 V1；再保存 → V2，V1 仍在。
- [ ] 生成中刷新页面不崩（草稿/状态见 §7）。

---

## 7. Phase 3 — 历史注入 + ICD-10 + 草稿（32–44h）P1

### 7.1 历史注入（function calling，两段式）HIST-2

```python
TOOL = {"type":"function","function":{
  "name":"get_patient_history",
  "description":"Retrieve this patient's prior finalized encounter notes.",
  "parameters":{"type":"object","properties":{"patient_id":{"type":"string"}},
                "required":["patient_id"]}}}

async def event_stream():
    has_history = await patient_has_notes(db, enc.patient_id)
    # ★ 复诊患者强制调用工具，保证「生成中确有工具调用」可演示且行为可证
    tool_choice = ({"type":"function","function":{"name":"get_patient_history"}}
                   if has_history else "auto")
    first = await client.chat.completions.create(
        model="gpt-4o", messages=messages, tools=[TOOL],
        tool_choice=tool_choice)                         # 非流式：先决策
    msg = first.choices[0].message
    if msg.tool_calls:
        history = await fetch_patient_history(db, enc.patient_id)  # 后端查库
        messages += [msg, {"role":"tool",
                           "tool_call_id":msg.tool_calls[0].id,
                           "content": json.dumps(history)}]
    # 第二段：带着(或不带)历史，流式产出 SOAP
    stream = await client.chat.completions.create(
        model="gpt-4o", messages=messages, stream=True, temperature=0.2)
    async for chunk in stream: ...   # 同 §6.1 转发
```

**为什么这样设计**：
- 满足「检索经后端工具调用、非前端塞历史」——历史从 DB 来，模型只拿到 `patient_id`。
- 复诊强制 `tool_choice` → demo 时一定能看到工具被调用，且「复诊引用历史 / 初诊独立」差异可证（HIST-4）。
- tradeoff：多一次非流式 round-trip（首 token 略慢）。可接受，换来真·工具调用语义。可优化为：无历史时跳过工具直接流式。

### 7.2 ICD-10 向量检索（ICD-2）

Seed：把 ~300 条 ICD-10（code, description）批量过 `text-embedding-3-small` 存库（启动/迁移时一次）。
```python
@router.get("/icd10/search")
async def icd_search(q: str, db=Depends(get_db)):
    qv = (await client.embeddings.create(
        model="text-embedding-3-small", input=q)).data[0].embedding
    rows = await db.execute(text("""
        SELECT code, description, 1-(embedding <=> :qv) AS score
        FROM icd10_codes ORDER BY embedding <=> :qv LIMIT 8
    """), {"qv": str(qv)})
    return rows.mappings().all()
```
前端控件：输入 → 防抖 → 显示 Top-8 → 点击 `appendToAssessment(code, desc)`。

**tradeoff**：pgvector 预算 embedding vs LLM 实时排序——前者查询只需一次 embedding + 索引扫描，低延迟低成本、可在 schema 评审展示向量列与 hnsw 索引；代价是建库步骤。符合需求「不依赖外部 ICD API + 内嵌 ≥200」。

### 7.3 草稿持久化（DRAFT-*）
- 前端对 transcript + working_note 做 **防抖(800ms) autosave** → `PUT /encounters/{id}/draft`，写 `encounters.working_note`/`transcript`，`status='draft'`。
- 登录后 `GET /encounters?status=draft&mine=1` 拉回未完成 encounter → 恢复编辑器。因存服务端，**跨设备**自然恢复（DRAFT-3）。
- tradeoff：autosave 频率——太频繁打 DB，太稀疏丢得多；防抖 + 仅在变更时写。

### 7.4 DoD
- [ ] 给已有历史的患者生成：日志可见 `get_patient_history` 被调用，笔记引用既往诊断；同转录换初诊患者则不引用。
- [ ] ICD 控件搜 "chest pain radiating to left arm" 返回相关码并可入 Assessment。
- [ ] 写一半 → 换浏览器登录 → 草稿恢复。

---

## 8. Phase 4 — Admin 控制台 + 实时模板（44–56h）P1

### 8.1 功能
- **全局 encounter 视图**（ADM-1）：`GET /admin/encounters?provider_id=&from=&to=`，server 端过滤 + 分页；表格密集展示。
- **provider 增/停**（ADM-2/3）：建账号（默认随机初始密码）；停用 = `is_active=false` + 写 `audit_log`。
- **模板 CRUD**（ADM-4）：增删改 templates；删用软删。

### 8.2 模板实时生效（ADM-6，关键）
机制很简单但要讲清：**生成时后端实时 `SELECT` 当前 template**（§6.1 的 `load_active_template`），而不是前端缓存模板内容。所以 admin 改完，provider 端**下一次生成**自然读到新值，无需刷新。
- tradeoff：无需 WebSocket 推送/SSE 通知前端——「实时」体现在「下次生成读最新库」，恰好满足需求措辞，且零额外复杂度。若要 UI 上即时反映模板列表变化，可加轮询或手动刷新按钮。

### 8.3 DoD
- [ ] admin 按 provider+日期筛选有效。
- [ ] 停用某 provider → 其下次请求 401。
- [ ] provider 工作区开着，admin 改模板 → provider 直接点 Generate，输出风格已变（不刷新）。

---

## 9. Phase 5 — 非 Happy-Path + Pioneer（56–64h）P1/P2

### 9.1 边界 1：无临床意义输入（EDGE-1）
生成前做**轻量门控**：要么独立分类调用，要么在 system prompt 要求——若转录无可识别临床内容，**只输出** `###INSUFFICIENT### <原因>`，前端识别该标记 → 显示「转录中未发现足够临床信息，请补充」而非渲染 SOAP。防幻觉。
```python
# system prompt 追加：
# "If the transcript contains no clinically meaningful content,
#  respond with exactly: ###INSUFFICIENT### <one-line reason>. Do NOT fabricate a note."
```

### 9.2 边界 2：保存时会话过期（EDGE-2）
- 因为 transcript/working_note 一直在 autosave，**保存时即使 401 也不丢数据**。
- 前端拦截 401 → 弹「会话已过期，请重新登录」→ 重登后自动重试保存（草稿仍在服务端）。
- 这正是 §7.3 草稿设计的「免费」收益——把边界 2 变成非事件。

### 9.3 Pioneer：版本差异对比（PIO-1，推荐）
- `GET /encounters/{id}/versions/{a}/diff/{b}` 或前端取两版本文本，用 `diff-match-patch` 做行内高亮。
- 性价比最高：复用已有版本数据，纯前端即可，演示「看见改了什么」极有说服力。
- 第二个可选：转录红旗预警（PIO-2）——生成前用一次便宜模型调用扫描危险信号，工作区顶部黄条提示。

### 9.4 DoD
- [ ] 粘贴一段闲聊文本 → 优雅拒绝，无编造 SOAP。
- [ ] 手动让 token 过期 → 保存 → 提示重登 → 重登后内容仍在并能保存。
- [ ] 选两个版本 → 看到红/绿高亮 diff。

---

## 10. Phase 6 — 打磨 + 硬化 + 演示稿（64–72h）P0

- **UI 收尾**：临床配色（白/深蓝灰/克制强调色），等宽数字、紧凑表格、清晰段落标题、加载/错误/空态完整。对照 function_list 总验收清单逐条走查。
- **基建复检**：再跑一遍 §4.5 DoD；准备「公网连 RDS 失败截图 / nginx conf / 连接池代码」三件套用于 walkthrough。
- **数据**：备好 1 个复诊患者（已有 2 条历史）+ 1 个初诊患者的演示脚本。
- **录屏脚本**：按总验收清单顺序演示，边演边讲决策。

---

## 11. Code Walkthrough 防御要点（逐条怎么讲）

| 评审会问 | 你的答法（一句话主线） |
|----------|------------------------|
| 为什么选 GPT-4o？ | 流式 + function calling 成熟稳定、低延迟、临床文档质量与格式遵循好；模型层做了 provider 封装，可一行切换。 |
| Prompt 怎么结构化？ | system(角色+严格四段格式+禁编造) + 模板注入(决定风格) + 工具(历史) + 转录；temperature 0.2 求稳定。 |
| 流式怎么实现的、真流式吗？ | FastAPI StreamingResponse(SSE) 转发 OpenAI 增量；nginx 关 buffering；前端 ReadableStream 增量按 `###段###` 归位。 |
| 历史为什么不前端塞？ | function calling：模型只拿 patient_id，后端查 RDS 返回 tool result；复诊强制工具调用，可演示且行为差异可证。 |
| Schema 为什么这样？ | 见 §2.3：users 单表+role、患者自然键、note_versions 追加式+唯一约束、ICD 受控词表独立、草稿同表、模板软删。 |
| 连接池在哪？ | SQLAlchemy async engine 应用启动建一次(全局单例)，pre_ping + recycle；FastAPI 依赖每请求借还，绝不每请求新建。 |
| RDS 怎么隔离？ | private subnet + publicly_accessible=No + 安全组按 ec2-sg 引用放行 5432；现场演示公网连不上、EC2 内连得上。 |
| 密钥怎么管？ | Secrets Manager + EC2 IAM Role，启动取一次缓存；仓库零明文，.env 不入库。 |
| 反代为什么不直接暴露 app？ | nginx 终止 TLS、托管静态、SSE 友好；app 只监听 127.0.0.1:8000；systemd 守护。 |

---

## 12. 时间告急时的砍/降级顺序

照 `function_list.md` 优先级**从下往上**砍。建议顺序：

1. 先砍 **PIO-2/3/4**，只保留 **PIO-1 Diff View**（甚至 Diff 也可降级为纯文本对比）。
2. **EDGE-3**（草稿中被停用）可不实现，保留 EDGE-1 + EDGE-2 两个即可。
3. Admin 的**模板 CRUD UI** 可降级为「预置好几个模板 + 只读切换」，但 **ADM-6 实时生效机制必须留**（讲得清即可）。
4. ICD 控件若紧张，可先保证**生成中的 ICD 建议(GEN-2)** 正确，搜索控件 UI 简化。
5. **绝不砍**：M0 基建、M1 鉴权隔离、M3 流式核心、M5 版本追加、INF-5/6/7（私网/连接池/密钥）。这些是评分地基，砍了等于失败。

> 验收哲学复述：**「对用户感觉完整 + 基建扎实」永远优先于「功能多但有明显裂缝」。**
