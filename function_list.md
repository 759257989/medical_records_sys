# AI Clinical Scribe Platform — 功能清单 (Function List)

> **技术栈**：FastAPI (Python) · React (Vite + TypeScript) · PostgreSQL + pgvector · OpenAI GPT-4o
> **部署**：AWS EC2（nginx 反代 + Let's Encrypt TLS）· RDS PostgreSQL（私有子网）· Secrets Manager
> **目标**：72h 单人完成，达到「物理医生愿意信任的临床工具」级别的完成度。

## 优先级图例

| 标记 | 含义 | 评分映射 |
|------|------|----------|
| **P0** | 必须万无一失（airtight）。做不好直接扣大分。 | 核心 scribe 流程 / 流式 / RDS 持久化 / 基础设施 |
| **P1** | 重要，体现产品完整度与工程能力。 | 历史注入 / 版本审计 / ICD-10 / Admin / 草稿 / 边界场景 |
| **P2** | 加分项（Pioneer）。锦上添花，时间不够可砍。 | 差异对比 / 写作风格学习 / 红旗预警 / PDF 导出 |

> 取舍原则：**「对用户感觉完整」+「基础设施扎实」> 「功能全但 UI/基建稀烂」**。任何 P2 都不能以牺牲 P0 稳定性为代价。

---

## M0 · 基础设施（Infrastructure）— P0

> 这是评分里最硬的一块，先做、先打通、保持可演示。

| ID | 功能 | 优先级 | 验收标准（Definition of Done） |
|----|------|--------|-------------------------------|
| INF-1 | EC2 托管应用 | P0 | 应用进程跑在 EC2，**不**直接暴露在 80/443，由 nginx 反代到 `127.0.0.1:8000`。 |
| INF-2 | HTTPS + 有效证书 | P0 | 通过域名访问，浏览器无警告；`openssl s_client` 显示 Let's Encrypt 链，**非自签**。 |
| INF-3 | nginx 反向代理 | P0 | nginx 终止 TLS、转发 API、托管前端静态包；支持 SSE（关闭 buffering）。 |
| INF-4 | RDS PostgreSQL | P0 | 所有持久数据落 RDS；无 SQLite / 本地文件 / 内存存储。 |
| INF-5 | RDS 私有隔离 | P0 | `publicly_accessible=false`；安全组仅放行来自 EC2 安全组的 5432；可现场用 `psql` 从公网连不上、从 EC2 能连上证明。 |
| INF-6 | 连接池 | P0 | SQLAlchemy async engine 在应用启动时创建一次（lifespan），`pool_pre_ping=True`；**绝不**每请求新建连接。 |
| INF-7 | Secrets 管理 | P0 | DB 凭证 + OpenAI Key 存 Secrets Manager，EC2 用 IAM Role 读取；仓库内无任何明文密钥（包括 `.env`）。 |
| INF-8 | 数据库迁移 | P0 | Alembic 管理 schema；`alembic upgrade head` 可重建全库。 |
| INF-9 | 进程守护 | P1 | gunicorn(uvicorn worker) + systemd，崩溃自启；重启后数据不丢。 |

---

## M1 · 认证与多角色访问（Auth & RBAC）— P0

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| AUTH-1 | 登录系统 | P0 | 邮箱+密码登录，密码 bcrypt 哈希存库；返回 JWT。 |
| AUTH-2 | 两种角色 | P0 | `provider` 与 `admin` 角色，路由级 + 数据级双重鉴权。 |
| AUTH-3 | 数据隔离 | P0 | Provider 只能读写**自己**的 encounter；越权访问返回 403（后端强制，非前端隐藏）。 |
| AUTH-4 | Admin 全局可见 | P0 | Admin 可查看所有 provider 的 encounter。 |
| AUTH-5 | 种子账号 | P0 | 预置 ≥3 个 provider + 1 个 admin，迁移 seed 脚本写入。 |
| AUTH-6 | Token 失效处理 | P1 | 过期/无效 token → 401；前端拦截并优雅处理（见 EDGE-2）。 |
| AUTH-7 | 停用即失效 | P1 | 账号被停用后，`is_active` 校验中间件令其 token 立即失效。 |

---

## M2 · Encounter 工作区（Provider View）— P0

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| ENC-1 | 新建 encounter | P0 | 录入患者 first name / last name / DOB 开始就诊。 |
| ENC-2 | 转录/观察输入 | P0 | 大文本区，可粘贴原始转录或自由书写临床观察。 |
| ENC-3 | 模板选择 | P1 | 生成前可选笔记模板（见 M8）。 |
| ENC-4 | 生成笔记按钮 | P0 | 点击 Generate，触发流式生成（见 M3）。 |
| ENC-5 | 行内编辑 | P0 | 生成后 SOAP 四段可直接行内编辑。 |
| ENC-6 | 保存笔记 | P0 | 保存定稿入库（触发版本写入，见 M5）。 |
| ENC-7 | 临床级 UI | P0 | 信息密集、克制、高信任感；非消费级气泡风。 |

---

## M3 · AI SOAP 生成 + 实时流式（Core Scribe）— P0

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| GEN-1 | 结构化 SOAP | P0 | 输出含 **S**ubjective / **O**bjective / **A**ssessment / **P**lan 四段。 |
| GEN-2 | ICD-10 建议 | P0 | Assessment 含 ≥1 个与临床内容**语义匹配**的 ICD-10 码 + 描述。 |
| GEN-3 | 真·流式渲染 | P0 | SSE 逐 token 渐进渲染，**非** spinner 后整段塞入；前端边收边显示分段。 |
| GEN-4 | 结构化解析 | P0 | 流式过程中能把 token 正确归位到对应 SOAP 段落。 |
| GEN-5 | 可中断/可重试 | P1 | 生成中断（网络/取消）有明确状态，可重试。 |
| GEN-6 | Prompt 工程 | P0 | 系统提示约束输出格式、临床语气、ICD 约束；可在 walkthrough 中讲清结构。 |

---

## M4 · 患者历史与上下文注入（Context Injection）— P1

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| HIST-1 | 患者匹配 | P1 | 按 first+last+DOB 匹配既有患者。 |
| HIST-2 | 后端工具调用注入 | P1 | 通过 **OpenAI function calling** 在生成中调用 `get_patient_history`，由后端查库返回历史——**不**在前端 prompt 里塞历史。 |
| HIST-3 | 临床引用 | P1 | 生成的笔记在临床合适处引用既往诊断/治疗。 |
| HIST-4 | 行为差异可证 | P1 | 同一转录，**复诊患者** vs **初诊患者**输出可明显区分（复诊引用历史，初诊独立）。 |

---

## M5 · 笔记版本与审计（Versioning & Audit）— P0

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| VER-1 | 追加式版本 | P0 | 每次「编辑+再保存」写**新版本**；旧版本永不覆盖/删除。 |
| VER-2 | 版本历史查看 | P1 | 可查看任一笔记完整版本历史。 |
| VER-3 | 谁·何时 | P1 | 每个版本记录 created_by + created_at。 |
| VER-4 | RDS 存储 | P0 | 版本历史存 RDS，非内存/文件。 |
| VER-5 | 管理操作审计 | P1 | 停用账号、改模板等管理动作写 `audit_log`。 |

---

## M6 · ICD-10 语义搜索控件（ICD-10 Search Widget）— P1

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| ICD-1 | 内嵌码库 | P1 | 内置 **≥200–300** 条 ICD-10 码（seed 入库），不依赖外部 API。 |
| ICD-2 | 向量检索 | P1 | pgvector 存预算 embedding；plain-English 查询 → 余弦相似度 Top-K。 |
| ICD-3 | 工作区内控件 | P1 | encounter 工作区内独立搜索控件。 |
| ICD-4 | 一键追加 | P1 | 点击结果即追加到当前笔记 Assessment 段。 |

---

## M7 · Admin 控制台（Admin Dashboard）— P1

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| ADM-1 | 全局 encounter 视图 | P1 | 跨所有 provider 查看，可按 provider + 日期范围筛选。 |
| ADM-2 | 新增 provider | P1 | 创建新 provider 账号。 |
| ADM-3 | 停用 provider | P1 | 停用账号（软停用，`is_active=false`）。 |
| ADM-4 | 模板 CRUD | P1 | 创建/编辑/删除笔记模板（结构化 prompt）。 |
| ADM-5 | 模板影响生成 | P1 | 不同模板令 AI 输出**可见地**不同（如骨科复诊 vs 新患者评估 vs 急诊）。 |
| ADM-6 | 模板实时生效 | P1 | Admin 改模板后，provider 工作区无需刷新，**下一次生成**即用新模板（生成时后端实时读库）。 |

---

## M8 · 会话持久化（Session Persistence）— P1

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| DRAFT-1 | 草稿入库 | P1 | 转录已输入、笔记未保存时，草稿自动存 RDS（防抖 autosave）。 |
| DRAFT-2 | 刷新恢复 | P1 | 刷新/关浏览器重开，草稿原样恢复。 |
| DRAFT-3 | 跨设备恢复 | P1 | 换浏览器/设备登录同账号，恢复同一草稿状态（因为存服务端）。 |

---

## M9 · 非 Happy-Path 场景（Edge Cases）— P1

> 至少实现并演示 **两个**。

| ID | 场景 | 优先级 | 验收标准 |
|----|------|--------|----------|
| EDGE-1 | 无临床意义输入 | P1 | 转录为空/无临床内容时，AI **优雅拒绝**（返回「内容不足」结构化提示），**不**编造 SOAP。 |
| EDGE-2 | 保存时会话过期 | P1 | 401 时前端不丢数据：编辑内容已 autosave 为草稿，提示重新登录后可继续保存。 |
| EDGE-3 | 草稿中被停用（可选第三个） | P2 | Admin 停用正在写草稿的 provider：草稿已存服务端，provider 被登出但数据不丢；可定义为「只读冻结 + 提示」。 |

---

## M10 · Pioneer 加分功能 — P2

> 建议挑 **1–2** 个。优先「便宜且演示效果好」的。

| ID | 功能 | 优先级 | 验收标准 |
|----|------|--------|----------|
| PIO-1 | **版本差异对比（Diff View）** | P2 | 两个版本间并排/行内 diff，高亮增删改。**性价比最高，强烈推荐**。 |
| PIO-2 | 转录红旗预警 | P2 | 生成前扫描转录，标记临床红旗（如胸痛+放射、自杀意念）。演示效果好。 |
| PIO-3 | Provider 写作风格学习 | P2 | 拉取该 provider 历史笔记，提炼用词/句式偏好注入 prompt，越用越像本人。 |
| PIO-4 | 患者全程 PDF 导出 | P2 | 把某患者跨所有就诊导出为单份结构化 PDF。 |

---

## 总验收清单（演示前自检）

- [ ] 全新患者：粘贴转录 → 流式生成完整 SOAP（含语义匹配 ICD-10）→ 行内改 → 保存。
- [ ] 复诊患者：同流程，生成中触发 `get_patient_history` 工具调用，笔记引用既往史。
- [ ] 同一笔记编辑两次 → 版本历史出现 V1/V2/V3，旧版可查，含人/时间。
- [ ] ICD-10 控件：输入「shortness of breath on exertion」→ 返回相关码 → 一键入 Assessment。
- [ ] Admin：筛选某 provider+日期；新增/停用 provider；改模板后 provider 端下次生成立即变。
- [ ] 草稿：写一半刷新/换浏览器 → 原样恢复。
- [ ] 边界 1：空转录 → 优雅拒绝。
- [ ] 边界 2：让 token 过期 → 保存时不丢数据。
- [ ] 基建：`curl` 验证 HTTPS 有效证书；公网连 RDS 失败、EC2 内连成功；展示 nginx 配置与连接池代码。
- [ ] Pioneer：Diff View 可演示。
