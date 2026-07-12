# Blade Rocking & Creep Test Management System

Full-stack turbine blade overhaul tracking system. FastAPI backend + React 18 frontend, containerized with Docker Compose.

See `docs/TECHNICAL_DESIGN.md` for the full technical design document.

---

## Project Layout

```
backend/app/
  main.py              FastAPI app factory
  core/config.py       All env vars (Pydantic Settings)
  models/              SQLAlchemy ORM (20 files)
  schemas/             Pydantic I/O schemas (10 files)
  api/v1/endpoints/    REST handlers (16 files: assembly, auth, batches, blades, dti, measurements, notifications, ocr, reports, slots, stations, sync, users, weighing, workflows, audit_logs)
  repositories/        DB queries (5 files)
  services/            Business logic
  workflows/state_machine.py   Blade status transitions
  notifications/       WebSocket + DB persistence
  ocr/                 Pluggable OCR providers
  reports/             Async Excel/PDF generation

frontend/src/
  pages/               Route-level views
  components/          Reusable UI (Radix UI + Tailwind)
  hooks/               Custom React hooks
  services/            Axios + React Query
  stores/              Zustand state

scripts/
  weighing_bridge.py   iScale i-04 RS-232 → backend WebSocket bridge
  dti_bridge.py        Sylvac BT DTI RS-232 → backend WebSocket bridge
  seed_data.py         Dev data seeder
```

---

## Key Commands

### Backend (run inside `backend/`)

```bash
# Dev server
uvicorn app.main:app --reload --port 8000

# Tests
pytest app/tests/ -v --cov=app --cov-fail-under=70

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "describe_change"

# Seed dev data
python ../scripts/seed_data.py
```

### Frontend (run inside `frontend/`)

```bash
npm run dev          # Vite dev server (port 5173)
npm run build        # Production build
npm run lint         # ESLint
npm run type-check   # tsc --noEmit
```

### Docker

```bash
make up              # Start all services
make down            # Stop all services
make logs            # Tail logs
make test            # Full test suite
```

---

## Blade Status Flow

```
CREATED → OH_INSPECTION → MEASUREMENTS_RECORDED → SENT_TO_ASSEMBLY
  → SLOT_ASSIGNED → BALANCING_IN_PROGRESS → BALANCING_COMPLETED
  → RETURNED_TO_OH → FINAL_VERIFICATION → COMPLETED

Any active state → REJECTED  (SUPER_ADMIN can → REOPENED → OH_INSPECTION)
Any active state → ON_HOLD
```

State transitions are enforced by `WorkflowEngine` in `backend/app/workflows/state_machine.py`. Never update `blade.status` directly — always go through `engine.transition()`.

---

## Auth & Roles

JWT-based auth. Four roles:

| Role | Key Permissions |
|------|----------------|
| `SUPER_ADMIN` | All access + user management + reopen blades |
| `OH_OPERATOR` | Create blades, record measurements, send to assembly |
| `ASSEMBLY_OPERATOR` | Assign slots, update balancing, return to OH |
| `QA_VIEWER` | Read-only |

Endpoints use `@require_roles(...)` decorator. Token blacklist is Redis-backed.

---

## Environment Setup

Copy `.env.example` to `.env`. Minimum required for local dev:

```bash
DATABASE_URL=postgresql+asyncpg://blade_user:password@localhost:5432/blade_rocking
SECRET_KEY=<run: python3 -c "import secrets; print(secrets.token_hex(32))">
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
OCR_PROVIDER=mock
```

---

## Architecture Notes

- **Async throughout:** asyncpg driver, SQLAlchemy async sessions, aiofiles. Never use sync DB calls in endpoint handlers.
- **Repository pattern:** All DB queries go through `backend/app/repositories/`. Services call repositories, never query the ORM directly.
- **Notifications:** `NotificationManager` holds WebSocket connections in memory. On server restart, in-flight connections drop; clients should reconnect. Persisted notifications in DB survive restarts.
- **Reports are async:** POST to `/reports/` returns immediately with `status=PENDING`. Poll `GET /reports/{id}` or wait for WebSocket push when `status=READY`.
- **OCR provider:** Controlled by `OCR_PROVIDER` env var. Default is `mock` — safe for dev. Switch to `tesseract` or `paddleocr` only on servers with those system packages installed.
- **Two-station deployment:** OH PC (701 Hanger) hosts the database. Assembly PC (720 Hanger) sets `DATABASE_URL` to point at the OH PC's PostgreSQL over LAN. No central server.
- **Batch size:** 90 LPTR + 90 HPTR = 180 blades per batch. Enforced per blade type via `BATCH_MAX_PER_TYPE = 90` in `endpoints/blades.py`.
- **Hardware bridges:** `scripts/weighing_bridge.py` (iScale i-04) and `scripts/dti_bridge.py` (Sylvac BT) are standalone processes, not part of the Docker Compose stack. Run on the workstation connected to the instruments.
- **Soft deletes:** `User` and `Blade` use `deleted_at` timestamp. Always filter `WHERE deleted_at IS NULL` — SQLAlchemy mixins in `models/base.py` handle this automatically.
- **Migrations:** Alembic autogenerate is used. After any model change, run `alembic revision --autogenerate` and review the generated script before applying.

---

## Testing Notes

- Tests use an in-process async SQLite (or Postgres) via `conftest.py` fixtures — no Docker required for unit/API tests.
- `fakeredis` is used for JWT blacklist tests — no real Redis needed.
- State machine tests in `tests/unit/test_workflow.py` are pure Python, no DB.
- Coverage gate is 70% — enforced in CI.
