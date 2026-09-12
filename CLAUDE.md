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

**Do NOT:** run the main `docker compose` stack / build the app / start Postgres on the second PC. There is exactly one app instance and one database — this OH PC. (The one narrow exception is `docker-compose.hptr-ocr.yml`, covered below — a single stateless OCR-inference container, not the app or a database.)

**Do, on the second PC:**
1. Copy over `scripts/` (at least `weighing_bridge.py`, `dti_bridge.py`, `oak1_camera_service.py`, `register_bridge_tasks.ps1`, `oak1_requirements.txt`) — cloning the whole repo is simplest since that keeps this file (`CLAUDE.md`) with it. Clone/copy it to the same path used elsewhere (`C:\blade-rocking`) — `register_bridge_tasks.ps1` hardcodes absolute interpreter paths under that root, not a relative one.
2. Install Python deps for the bridge scripts there:
   - `weighing_bridge.py` / `dti_bridge.py` use the plain system Python (`register_bridge_tasks.ps1`'s `$py`).
   - `oak1_camera_service.py` needs its **own dedicated venv** at `scripts\oak1-venv` — `depthai` doesn't coexist cleanly with the other scripts' deps. Create it and install into it explicitly:
     ```
     python -m venv scripts\oak1-venv
     scripts\oak1-venv\Scripts\pip install -r scripts\oak1_requirements.txt
     ```
     `register_bridge_tasks.ps1` points the OAK-1 task at `scripts\oak1-venv\Scripts\pythonw.exe` specifically (`$oak1Py`) — if that venv doesn't exist at that exact path, the task will register and appear to start, but the process will crash immediately on `import depthai` and the task will silently stay dead (check `Get-ScheduledTaskInfo -TaskName "BladeRocking-OAK1CameraService"` → `LastTaskResult` if the camera won't come up).
3. In an elevated PowerShell, register the bridges pointed at the OH PC instead of localhost, **with a `-Station` value not used by any other PC**:
   ```
   powershell -ExecutionPolicy Bypass -File register_bridge_tasks.ps1 -Server http://172.146.5.98 -Station 2
   ```
   (`-Server` defaults to `http://localhost`, which is only correct when bridge and backend are on the same machine — omit it when running this script on the OH PC itself. `-Station` defaults to `1`, matching the OH PC's own scale/gauge — every other PC with its own scale/gauge MUST pass a different value, e.g. `2`, or its readings collide with the OH PC's: `weighing_bridge.py`/`dti_bridge.py` scope every reading by station server-side, but two bridges pushing the same station id are indistinguishable to the backend.) The OAK-1 camera service never takes a `-Server` or `-Station` value — it always talks to its own `localhost:8089`, never the OH PC, and has no reading-collision concern since it isn't a broadcast channel.
4. Operators on that PC open a browser to `http://172.146.5.98/?station=2` (or `http://bladerocking-1-/?station=2`) — **the `?station=` must match step 3's `-Station`** — and log in with the appropriate role. The OH PC's own bookmark stays `http://172.146.5.98/` with no `?station=` (defaults to `1`), unaffected by any of this.

The OH PC's LAN address/hostname is not a magic constant — if it ever changes, update it in `.env.oh` (`CORS_ORIGINS`) and in `scripts/oak1_camera_service.py`'s `DEFAULT_ORIGINS`, and re-run step 3 above with the new address on every secondary PC.

### Optional: running OCR inference on the secondary station too

PaddleOCR inference is CPU-heavy (five preprocessing variants x two language engines per scan — see `backend/app/ocr/paddle_provider.py`). If the OH PC's backend is doing OCR for its own station *and* a secondary station at the same time, that's real, non-hypothetical load on one process. `scripts/hptr_ocr_service.py` is a standalone companion service (same category as the bridges — not part of the main stack) that runs PaddleOCR **on the secondary station's own hardware** instead: it saves the captured image locally on that station, forwards only the small JSON detection result to the OH backend (`POST /ocr/scan/ingest-detection`, no image), and uploads the actual image to the OH backend in the background afterward (`POST /ocr/scan/{scan_id}/image`) so the blade record's attachment/audit view and the OCR training-dataset export end up with it exactly as if the scan had run centrally — the operator isn't kept waiting on that upload.

This does **not** contradict "exactly one app instance and one database" above — this service has no database of its own and stores nothing durable except a working copy of images it's about to forward; the OH PC's Postgres is still the only source of truth for blade records.

It's the one piece of a secondary station's setup that runs cleanly in Docker instead of a native venv, since — unlike the bridges — it never touches local hardware directly, only images already captured and handed to it over HTTP:
```
OH_SERVER_URL=http://172.146.5.98 docker compose -f docker-compose.hptr-ocr.yml up -d --build
```
(A native-venv path also exists — `scripts\ocr-venv` + `scripts/hptr_ocr_requirements.txt`, registered via `register_bridge_tasks.ps1`'s `BladeRocking-HPTROCRService` task — for a station that can't run Docker. Same silent-failure caveat as the OAK-1 venv applies if `scripts\ocr-venv` doesn't exist at that path.)

The frontend decides per-browser, at runtime, whether to use it (`GET http://localhost:8090/health`) rather than via a build-time flag, since one frontend build is served to every station (see `frontend/src/services/localOcr.ts`) — a station with the container/service running gets local OCR automatically; every other station falls straight through to the central endpoint with no configuration needed.

`PaddleOCRProvider` is constructed with `script_bias="english"` in `hptr_ocr_service.py`, not the `"cyrillic"` default the OH-station backend uses — the fusion tuning behind `OCR_PROVIDER=paddleocr` (canonicalizing the ambiguous embedded letter to Cyrillic, preferring a pure-Cyrillic read) was calibrated against a ground-truth sample that skewed Cyrillic; this station's HPTR blades read more Latin/English on the stamp, so the same provider class runs here with that preference flipped instead of duplicating the fusion logic. See the class docstring in `backend/app/ocr/paddle_provider.py` for exactly what `script_bias` changes.

Camera capture only works over a secure context: `https://`, or literally `http://localhost`/`127.0.0.1` — a plain-HTTP LAN hostname/IP (e.g. `http://bladerocking-1-`, `http://172.146.5.98`) is *not* secure in the browser's eyes, so `navigator.mediaDevices` is `undefined` there and the browser-webcam fallback in `CameraModal.tsx`/`CameraScanner.tsx` can never work on any station accessed that way — this is a browser restriction, not something fixable in this app's code. That's exactly why every station is expected to have its own OAK-1 (or another local capture path) rather than relying on the in-browser webcam: OAK-1 capture goes through `oak1_camera_service.py`'s plain HTTP fetch on `localhost`, which isn't subject to this restriction at all.

For a station that must use the in-browser webcam fallback anyway (no OAK-1 attached), Chrome/Edge's `OverrideSecurityRestrictionsOnInsecureOrigin` enterprise policy can whitelist specific plain-HTTP origins as secure contexts. Run `scripts/allow_insecure_camera_origin.ps1` (elevated PowerShell, on the station PC) to set it for the OH PC's LAN address/hostname; it defaults to the same two origins as `CORS_ORIGINS` in `.env.oh` and `DEFAULT_ORIGINS` in `oak1_camera_service.py` — keep all three in sync if the OH PC's address ever changes. Requires a full browser restart to take effect; verify at `chrome://policy` / `edge://policy`.

OCR inference (PaddleOCR) runs centrally in the OH PC's backend container by default — a secondary PC's camera just captures and uploads images over the network, no PaddleOCR installed locally. The exception is a station running `scripts/hptr_ocr_service.py` (see "Optional: running OCR inference on the secondary station too" above), which does run PaddleOCR locally specifically to take that load off the OH PC.

---

## Testing Notes

- Tests use an in-process async SQLite (or Postgres) via `conftest.py` fixtures — no Docker required for unit/API tests.
- `fakeredis` is used for JWT blacklist tests — no real Redis needed.
- State machine tests in `tests/unit/test_workflow.py` are pure Python, no DB.
- Coverage gate is 70% — enforced in CI.
