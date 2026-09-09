# Blade Rocking & Creep Test Management System

Full-stack turbine blade overhaul tracking system. FastAPI backend + React 18 frontend, containerized with Docker Compose.

See `docs/TECHNICAL_DESIGN.md` for the full technical design document.

---

## Project Layout

```
backend/app/
  main.py              FastAPI app factory
  core/config.py       All env vars (Pydantic Settings)
  models/              SQLAlchemy ORM (incl. work_order.py, lptr_balancing_check.py)
  schemas/             Pydantic I/O schemas (incl. work_order.py, lptr_balancing.py)
  api/v1/endpoints/    REST handlers (17 files: assembly, auth, blades, dti, lptr_balancing, measurements, notifications, ocr, reports, slots, stations, sync, users, weighing, work_orders, workflows, audit_logs)
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
  weighing_bridge.py        iScale i-04 RS-232 → backend WebSocket bridge
  dti_bridge.py             Sylvac BT DTI RS-232 → backend WebSocket bridge
  oak1_camera_service.py    Luxonis OAK-1 Flask companion (port 8089)
  register_bridge_tasks.ps1 Register bridges as Windows Scheduled Tasks (run once as Admin)
  run_native.sh             Start full stack natively without Docker
  stop_native.sh            Stop native stack
  seed_data.py              Dev data seeder
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

**14 states** (ON_HOLD removed). LPTR and HPTR follow different paths:

```
# LPTR (full path through Assembly)
CREATED → OH_INSPECTION → MEASUREMENTS_RECORDED → SENT_TO_ASSEMBLY
  → ASSEMBLY_RECEIVED → ASSEMBLY_VERIFIED → SLOT_ASSIGNED
  → BALANCING_IN_PROGRESS → BALANCING_COMPLETED
  → RETURNED_TO_OH → FINAL_VERIFICATION → COMPLETED

# HPTR (stays at OH — extra edges via EXTRA_TRANSITIONS_BY_TYPE)
CREATED → OH_INSPECTION → MEASUREMENTS_RECORDED → SLOT_ASSIGNED
  → BALANCING_IN_PROGRESS → BALANCING_COMPLETED → FINAL_VERIFICATION → COMPLETED

Any active state → REJECTED  (SUPER_ADMIN can → REOPENED → OH_INSPECTION)
```

State transitions are enforced by `WorkflowEngine` in `backend/app/workflows/state_machine.py`. Never update `blade.status` directly — always go through `engine.transition()`. HPTR extra edges are in `EXTRA_TRANSITIONS_BY_TYPE`.

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
- **Work Orders replace Batches:** Blades are created 90 at a time via a Work Order. `serial_number` is a positional S.No (01–90), unique per work order — not globally. `batches` endpoint is gone; use `work-orders`.
- **Reports are async:** POST to `/reports/generate` returns immediately with `status=PENDING`. Poll `GET /reports/{id}` or wait for WebSocket push when `status=READY`. Runs as a FastAPI `BackgroundTasks` coroutine in-process on the request worker — not Celery (`celery`/`redis` remain in `requirements.txt` and `app/worker.py`/`app/reports/tasks.py` still exist, but nothing in the request path invokes them; no durable queue, no retry if the process crashes mid-generation). Four sync export endpoints (`/reports/export/...`) return files directly.
- **OCR provider:** Controlled by `OCR_PROVIDER` env var. Default is `paddleocr`. Use `mock` for dev without PaddleOCR installed.
- **Single-server deployment:** The OH PC (701 Hanger) runs the entire stack (`docker-compose.oh.yml`) — Postgres, backend, frontend, nginx. Assembly (720 Hanger) has no local install: staff just open a browser to `http://<OH_PC_IP>/` on the plant LAN and log in with an `ASSEMBLY_OPERATOR` account; role-based access (see Auth & Roles above) is what actually restricts what they can do, not which PC they're on. There used to be a separate Assembly-side Docker stack (`docker-compose.assembly.yml`) running its own backend against OH's Postgres over LAN — removed as unnecessary once it became clear Assembly has no local hardware (no OCR camera, scale, or DTI gauge) that would need a local backend to bridge into. `STATION_ROLE` still exists in `core/config.py` (`OH` vs `ASSEMBLY`) and the read-only `/sync/*` endpoints still exist for a hypothetical second backend instance, but neither is exercised by the current single-server setup — don't build against them without confirming they're still wanted.
- **Work Order size:** 90 blades per Work Order, one blade type only (LPTR or HPTR). Constant: `BLADES_PER_WORK_ORDER = 90`.
- **Hardware bridges:** `weighing_bridge.py`, `dti_bridge.py`, and `oak1_camera_service.py` are standalone processes outside Docker Compose. Register as Windows Scheduled Tasks via `scripts/register_bridge_tasks.ps1`.
- **Soft deletes:** `User` and `Blade` use `deleted_at` timestamp. Always filter `WHERE deleted_at IS NULL` — SQLAlchemy mixins in `models/base.py` handle this automatically.
- **Migrations:** Alembic autogenerate is used. After any model change, run `alembic revision --autogenerate` and review the generated script before applying.

---

## Secondary Hardware Stations (e.g. a second PC in 701 Hanger for HPTR)

Same idea as the OH/Assembly split: a second PC can share this same app instead of running its own stack. This applies when a PC has hardware physically attached (DTI gauge, weighing scale, OAK-1 camera) but should **not** host its own copy of the app or database — everything stays centralized on the OH PC so both LPTR and HPTR work land in one database (the workflow engine already tells them apart via `blade_type` / `EXTRA_TRANSITIONS_BY_TYPE`).

**Do NOT:** run `docker compose` / build the app / start Postgres on the second PC. There is exactly one app instance and one database — this OH PC.

**Do, on the second PC:**
1. Copy over `scripts/` (at least `weighing_bridge.py`, `dti_bridge.py`, `oak1_camera_service.py`, `register_bridge_tasks.ps1`, `oak1_requirements.txt`) — cloning the whole repo is simplest since that keeps this file (`CLAUDE.md`) with it.
2. Install Python deps for the bridge scripts there (see `oak1_requirements.txt`).
3. In an elevated PowerShell, register the bridges pointed at the OH PC instead of localhost:
   ```
   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -Server http://172.146.5.98
   ```
   (`-Server` defaults to `http://localhost`, which is only correct when bridge and backend are on the same machine — omit it when running this script on the OH PC itself.) The OAK-1 camera service never takes a `-Server` value — it always talks to its own `localhost:8089`, never the OH PC.
4. Operators on that PC just open a browser to `http://172.146.5.98/` (or `http://bladerocking-1-`, the OH PC's Windows/NetBIOS hostname — works LAN-wide with no DNS setup) and log in with the appropriate role.

The OH PC's LAN address/hostname is not a magic constant — if it ever changes, update it in `.env.oh` (`CORS_ORIGINS`) and in `scripts/oak1_camera_service.py`'s `DEFAULT_ORIGINS`, and re-run step 3 above with the new address on every secondary PC.

OCR inference itself (PaddleOCR) always runs centrally in the OH PC's backend container — a secondary PC's camera only captures and uploads images over the network; it never needs PaddleOCR installed locally.

---

## Testing Notes

- Tests use an in-process async SQLite (or Postgres) via `conftest.py` fixtures — no Docker required for unit/API tests.
- `fakeredis` is used for JWT blacklist tests — no real Redis needed.
- State machine tests in `tests/unit/test_workflow.py` are pure Python, no DB.
- Coverage gate is 70% — enforced in CI.
