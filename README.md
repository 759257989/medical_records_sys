<p align="center">
  <img src="MedNoteCopilot.png" alt="MedNote Copilot" width="360" />
</p>

<h1 align="center">MedNote Copilot</h1>

<p align="center">
  An AI clinical documentation platform that turns a raw visit transcript into a
  structured, editable SOAP note — with streaming generation, ICD-10 coding, and
  patient-history awareness.
</p>

---

## What it does

A physician pastes a visit transcript (or types free-form notes), and the AI returns a structured **SOAP note** (Subjective, Objective, Assessment, Plan) with suggested **ICD-10 codes** — rendered live as it generates.

**Provider**
- **Streaming SOAP generation** from a transcript (real-time, server-sent events — no spinner-then-dump).
- **Semantic ICD-10 search** (vector similarity) — type a symptom in plain English, click to add it to the note.
- **Patient-history aware** — for returning patients, the AI pulls prior notes via a backend **function call** (not stuffed into the frontend prompt) and writes a different note accordingly.
- **Version history** — every save is a new immutable version; **diff view** highlights what changed.
- **Draft autosave & session persistence** — refresh or switch devices and continue where you left off.

**Admin**
- View **all encounters** across providers, filter by provider and date range.
- **Add / deactivate** provider accounts (deactivation takes effect immediately).
- Manage **note templates** that shape the AI's output — edits apply on the provider's **next generation with no page refresh**.
- Every admin action is written to an **audit log**.

**Robustness**
- Graceful handling of edge cases: a transcript with no clinical content is **not** turned into a hallucinated note; an expired session shows a re-login prompt **without losing the draft**; deactivating a provider mid-draft locks them out but keeps their work safe.
- Real auth: **JWT** with two roles (provider / admin), bcrypt passwords, and an active-account check on every request.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.11+), SQLAlchemy (async) |
| Frontend | React + TypeScript (Vite) |
| Database | PostgreSQL 16 + [pgvector](https://github.com/pgvector/pgvector) |
| AI | OpenAI **GPT-4o** (notes) + `text-embedding-3-small` (ICD search) |
| Infra | AWS EC2 + RDS (private) + nginx + Let's Encrypt + Secrets Manager |

---

## Project structure

```
backend/      FastAPI app, SQLAlchemy models, Alembic migrations, seed scripts
frontend/     React + Vite + TypeScript SPA
guides/       Step-by-step build docs, AWS deployment runbook, demo script
docker-compose.yml   Local PostgreSQL (pgvector) on port 5433
```

---

## Getting started (local)

### Prerequisites
- **Docker** (for the local database)
- **Python 3.11+**
- **Node 20 or 22** 
- An **OpenAI API key** (required for note generation)

### 1. Start the database
```bash
docker compose up -d        # PostgreSQL + pgvector on localhost:5433
```

### 2. Backend
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # then edit .env (see below)
alembic upgrade head         # create tables + pgvector extension + index
python -m app.seed           # seed demo accounts + templates
python -m app.seed_icd       # seed ICD-10 codes (+ embeddings if a key is set)

uvicorn app.main:app --reload --port 8000
```

Edit `backend/.env`:
```env
# NOTE: local DB is exposed on host port 5433 (see docker-compose.yml)
DATABASE_URL=postgresql+asyncpg://scribe:scribe_local_pw@localhost:5433/scribe
JWT_SECRET=<run: openssl rand -hex 32>
JWT_EXPIRE_HOURS=8
OPENAI_API_KEY=sk-...
ENVIRONMENT=local
```

### 3. Frontend
```bash
cd frontend
nvm use 20                   # Node 20 or 22
npm install
npm run dev                  # http://localhost:5173
```

Open **http://localhost:5173**.

### Demo accounts
| Role | Email | Password |
|---|---|---|
| Provider | `dr.smith@clinic.example.com` | `Provider123!` |
| Provider | `dr.jones@clinic.example.com` | `Provider123!` |
| Provider | `dr.lee@clinic.example.com` | `Provider123!` |
| Admin | `admin@clinic.example.com` | `Admin123!` |

---

## Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | Async Postgres URL (`postgresql+asyncpg://…`); use port **5433** locally |
| `JWT_SECRET` | Secret for signing JWTs (`openssl rand -hex 32`) |
| `JWT_EXPIRE_HOURS` | Token lifetime (default 8) |
| `OPENAI_API_KEY` | Required for SOAP generation and ICD embeddings |
| `ENVIRONMENT` | `local` or `aws` |

---

## Architecture & Technical Decisions

```
                        Browser (React SPA)
                              │  HTTPS
                              ▼
                    nginx  (TLS · serves SPA · reverse-proxies /api · no buffering for SSE)
                              │  127.0.0.1:8000
                              ▼
                    FastAPI  (JWT auth · streaming · function calling)
                          │                         │
            connection pool│                         │ OpenAI API
                          ▼                         ▼
        RDS PostgreSQL 16 + pgvector        GPT-4o · text-embedding-3-small
        (private subnet, not public)
```

**Streaming (SSE).** The backend returns the model output as a `text/event-stream`; the frontend reads the stream and parses the SOAP sections as they arrive, so the note renders live instead of appearing all at once. In production, nginx has `proxy_buffering off` on `/api` so the stream is not batched.

**Patient history via function calling.** For a returning patient, the model is given a `get_patient_history` tool. When it calls the tool, the backend queries RDS for the patient's prior notes and feeds them back as a tool message. The frontend never receives the raw history — it stays server-side, which is both cleaner and more secure than injecting records into a client-side prompt.

**Model choice & prompt design.** GPT-4o was chosen for reliable tool-calling and solid clinical reasoning. The system prompt enforces a strict output contract: return the four SOAP sections with fixed markers, never fabricate facts that aren't in the transcript, and emit an `INSUFFICIENT` marker when the transcript has no clinical content — which is what powers the graceful edge-case handling.

**Semantic ICD-10 search.** ~200+ ICD-10 codes are embedded with `text-embedding-3-small` (1536-dim) and stored in Postgres via **pgvector** with an **HNSW** index. Plain-English queries are embedded and matched by cosine distance, so results are semantic, not keyword-based (with a keyword fallback if no API key is set).

**Normalized schema & immutable versions.** Separate tables for users, patients, encounters, note versions, templates, ICD codes, and an audit log, connected with foreign keys. Note versions are **append-only** with a `UNIQUE(encounter_id, version_no)` constraint, so history can never be overwritten. Every admin action is written to the audit log **in the same transaction** as the change.

**Real-time templates.** The active template is read from the database **at generation time**, so an admin's edit takes effect on the provider's next generation with no caching and no page refresh.

**Connection pooling.** A single async SQLAlchemy engine maintains one pool (`pool_size=10`, `max_overflow=5`, pre-ping, 30-min recycle). The app never opens a new database connection per request.

**Auth & RBAC.** JWT (HS256, 8-hour expiry) with bcrypt-hashed passwords. Every request re-checks that the account is still active, so a deactivated provider is locked out immediately. Encounter ownership is enforced on the backend — providers can only access their own data.

**Production infrastructure (AWS).** nginx handles TLS and serves both the SPA and the API; the app process (uvicorn) only listens on `127.0.0.1:8000` and is never directly exposed. RDS runs in a **private subnet** and is **not publicly accessible** — it only accepts connections from the app's security group. All secrets are stored in **AWS Secrets Manager** and read at startup via an EC2 IAM role; nothing sensitive is committed to the repo.

