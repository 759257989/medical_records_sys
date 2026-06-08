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

