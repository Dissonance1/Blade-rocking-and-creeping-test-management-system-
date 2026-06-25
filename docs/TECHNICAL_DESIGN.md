# Technical Design Document
## Blade Rocking & Creep Test Management System

**Version:** 1.1  
**Owner:** Meridian Data Labs  
**Contact:** amit@meridiandatalabs.com

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Data Model](#4-data-model)
5. [Blade Workflow State Machine](#5-blade-workflow-state-machine)
6. [API Reference](#6-api-reference)
7. [Authentication & RBAC](#7-authentication--rbac)
8. [Real-Time & Async Processing](#8-real-time--async-processing)
9. [Hardware Integration](#9-hardware-integration)
10. [OCR Integration](#10-ocr-integration)
11. [Report Generation](#11-report-generation)
12. [IRS (Inspection Record Sheet) Format](#12-irs-inspection-record-sheet-format)
13. [Infrastructure & Deployment](#13-infrastructure--deployment)
14. [Security](#14-security)
15. [Testing](#15-testing)
16. [Configuration Reference](#16-configuration-reference)

---

## 1. System Overview

The Blade Rocking & Creep Test Management System tracks turbine blades through their complete overhaul (OH) lifecycle: incoming inspection, dimensional measurement (rocking/creep tests), assembly slot allocation, dynamic balancing, and final quality verification before return to service.

### Business Problem

Turbine blades undergo periodic overhaul cycles. Each blade must be individually measured (weight, static moment, rocking value, creep value, height positions), grouped into compatible sets for a given engine, allocated to assembly slots, balanced, and re-verified before dispatch. Paper-based tracking and spreadsheets create traceability gaps and audit failures. This system replaces that process with a digital workflow that enforces sequencing, captures measurements directly from instruments, and produces exportable traceability reports.

### Core Capabilities

- Blade registration and identity verification (serial number, melt number, part number)
- Multi-stage dimensional measurement capture with automated static moment calculation
- Batch-level tracking when blades move between OH and Assembly departments (max 90 blades per batch)
- Slot allocation and dynamic balancing record-keeping
- Rejection workflow with reason classification and SUPER_ADMIN-controlled reopening
- Async PDF/Excel report generation for compliance and shipping packages
- Real-time WebSocket notifications across operator workstations
- QR code generation per blade for mobile scanning
- OCR scanning of blade markings to cross-check manual entry
- Serial-port bridge to digital weighing scales
- Full immutable audit trail at both HTTP and domain-event levels

---

## 2. Architecture

### High-Level Stack

```
┌─────────────────────────────────────────────────────────────┐
│                        NGINX (port 80/443)                   │
│              Reverse proxy + static file server              │
└─────────────┬───────────────────────┬───────────────────────┘
              │                       │
              ▼                       ▼
   ┌─────────────────┐     ┌──────────────────────┐
   │  React 18 SPA   │     │   FastAPI (uvicorn)   │
   │  TypeScript     │     │   Python 3.11         │
   │  Vite / Tailwind│     │   Async (asyncpg)     │
   └─────────────────┘     └──────────┬───────────┘
                                      │
              ┌───────────────────────┼────────────────────┐
              ▼                       ▼                     ▼
   ┌──────────────────┐  ┌─────────────────┐  ┌───────────────────┐
   │  PostgreSQL 15   │  │   Redis 7        │  │  Celery Worker    │
   │  Primary store   │  │  JWT blacklist   │  │  Report gen tasks │
   │  (async SQLAlch) │  │  Celery broker   │  │  (openpyxl /      │
   └──────────────────┘  │  Result backend  │  │   ReportLab)      │
                         └─────────────────┘  └───────────────────┘
```

### Layer Breakdown

| Layer | Technology | Responsibility |
|-------|-----------|----------------|
| API Gateway | NGINX 1.27 | TLS termination, rate limiting, static assets |
| Web Framework | FastAPI 0.111 | Route handling, dependency injection, WebSocket |
| ORM | SQLAlchemy 2.0 (async) | Database queries via asyncpg |
| Validation | Pydantic v2 | Request/response schema enforcement |
| Auth | PyJWT + bcrypt | JWT creation/validation, password hashing |
| Task Queue | Celery 5.4 + Redis | Background report generation |
| State Machine | Custom (workflows/state_machine.py) | Blade status transition enforcement |
| Notifications | WebSocket (in-memory pool) + DB | Real-time push + persistent unread count |
| OCR | Pluggable (mock / Tesseract / PaddleOCR) | Blade marking extraction |
| Hardware | pyserial | Weighing scale + DTI gauge serial bridges |

### Request Lifecycle

```
Client → NGINX → FastAPI router
              → Auth middleware (JWT decode)
              → AuditMiddleware (log request)
              → Rate limit check (SlowAPI)
              → Permission check (@require_roles)
              → Endpoint handler
                  → Pydantic schema validation
                  → Service layer (business logic)
                      → Repository (DB query)
                      → WorkflowEngine (state transition)
                      → NotificationService (push)
              → Pydantic response schema
              → AuditMiddleware (log response)
              → Client
```

---

## 3. Directory Structure

```
blead_rocking/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory + lifespan hooks
│   │   ├── worker.py                # Celery app config
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings (40+ env vars)
│   │   │   ├── dependencies.py      # get_db(), get_current_user()
│   │   │   ├── security.py          # JWT create/decode, bcrypt
│   │   │   └── jwt_blacklist.py     # Redis-backed token revocation
│   │   ├── db/
│   │   │   ├── base.py              # DeclarativeBase + reusable mixins
│   │   │   └── session.py           # Async engine factory, get_db()
│   │   ├── models/                  # SQLAlchemy ORM entities (20 files)
│   │   ├── schemas/                 # Pydantic I/O schemas (10 files)
│   │   ├── api/v1/
│   │   │   ├── router.py            # Top-level router, 12 sub-routers
│   │   │   └── endpoints/           # One module per domain (12 files)
│   │   ├── repositories/            # Data access layer (5 files)
│   │   ├── services/                # Business logic (blade, weighing)
│   │   ├── workflows/
│   │   │   └── state_machine.py     # ALLOWED_TRANSITIONS + WorkflowEngine
│   │   ├── notifications/           # WebSocket manager + persistence
│   │   ├── ocr/                     # Pluggable OCR provider registry
│   │   ├── reports/                 # Excel/PDF generator + Celery tasks
│   │   ├── middleware/              # Audit logging, rate limiting
│   │   └── tests/                   # pytest suite (conftest + 5 test files)
│   ├── alembic/                     # Schema migrations
│   │   └── versions/                # 3 migration scripts
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/              # Reusable UI (Radix UI + Tailwind)
│   │   ├── pages/                   # Route-level views
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── services/                # Axios API client + React Query
│   │   ├── stores/                  # Zustand state
│   │   └── types/                   # TypeScript type definitions
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── scripts/
│   ├── seed_data.py                 # Dev/demo data seeder
│   ├── seed_demo_data.py
│   ├── manage_batches.py            # Batch management CLI
│   ├── weighing_bridge.py          # Weighing scale RS-232 → API bridge
│   └── dti_bridge.py               # DTI gauge RS-232 → API bridge
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
├── Makefile
└── .github/workflows/ci.yml
```

---

## 4. Data Model

### Entity Relationship Overview

```
User ──────────────────────────────────────────────────────────┐
  │ (created_by, assigned_to,                                  │
  │  measured_by, approved_by,                                 │
  │  allocated_by, action_by)                                  │
  │                                                            │
Blade ◄── Measurement (weight, rocking, creep, height)        │
  │                                                            │
  ├──► SlotAllocation (slot_number, balanced, unbalance)      │
  ├──► WorkflowLog (from→to, timestamp, remarks, metadata)   │
  ├──► Attachment (file_path, mime_type, ocr_scan)            │
  ├──► Notification (title, body, is_read, expires_at)        │
  └──► BatchEvent (via batch_number)                          │
                                                              │
BatchGroup (batch_number → work_order/part/engine metadata)   │
                                                              │
Station ◄── Blade (current_station)                           │
Station ◄── User (home_station)                               │
                                                              │
Role ◄──► Permission (resource + action pairs)                │
User ◄──► Role (user_roles junction)                         ◄┘
```

### Blade (Central Entity)

The `blades` table is the system's primary entity. Key fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `serial_number` | VARCHAR(64) UNIQUE | Physical blade identifier |
| `melt_number` | VARCHAR(64) | Material traceability |
| `work_order_number` | VARCHAR(64) | MRO work order |
| `shop_order_number` | VARCHAR(64) | Internal shop order |
| `part_number` | VARCHAR(64) | Drawing/part number |
| `nomenclature` | VARCHAR(128) | Human-readable component name |
| `engine_number` | VARCHAR(64) | Parent engine |
| `engine_hours` | VARCHAR(64) | Engine total hours at removal |
| `component_hours` | VARCHAR(64) | Blade individual hours at removal |
| `batch_number` | VARCHAR(64) | Grouping key for assembly batches |
| `blade_type` | ENUM | `LPTR` or `HPTR` |
| `status` | ENUM | 13 states (see state machine) |
| `current_station_id` | UUID FK → stations | |
| `created_by_id` | UUID FK → users | |
| `assigned_to_id` | UUID FK → users | |
| `ocr_serial_number` | VARCHAR(64) | OCR-extracted serial |
| `ocr_melt_number` | VARCHAR(64) | OCR-extracted melt number |
| `ocr_mismatch_flag` | BOOLEAN | Set when OCR disagrees with manual entry |
| `ocr_mismatch_notes` | TEXT | Explanation of the mismatch |
| `rejection_reason_id` | UUID FK → rejection_reasons | |
| `rejection_notes` | TEXT | |
| `deleted_at` | TIMESTAMP | Soft delete |

### Measurement

Stores each physical measurement session against a blade:

| Field | Type | Notes |
|-------|------|-------|
| `measurement_type` | ENUM | `INITIAL`, `INTERIM`, `FINAL` |
| `weight_grams` | NUMERIC(12,4) | |
| `static_moment_gcm` | NUMERIC(12,4) | Auto-calculated: weight × 1.57 × 20 |
| `rocking_value` | NUMERIC(12,6) | Core rocking test result |
| `creep_value` | NUMERIC(12,6) | LPTR blades only |
| `height_data` | JSONB | `{"H1": 12.3, "H2": 11.9, ...}` |
| `station_id` | UUID FK → stations | Station where measured |
| `is_approved` | BOOLEAN | QA sign-off |
| `approved_by_id` | UUID FK → users | |
| `approved_at` | TIMESTAMP | |

**Auto-transition:** When a measurement is recorded on a blade in `OH_INSPECTION`, the blade automatically transitions to `MEASUREMENTS_RECORDED`.

### Users & RBAC

```
users ──► user_roles ──► roles ──► role_permissions ──► permissions
```

Four built-in roles:

| Role | Capabilities |
|------|-------------|
| `SUPER_ADMIN` | Full access, user management, reopen rejected blades |
| `OH_OPERATOR` | Create blades, record measurements, send to assembly |
| `ASSEMBLY_OPERATOR` | Assign slots, update balancing, return to OH |
| `QA_VIEWER` | Read-only access across all entities |

User fields include `last_login` timestamp (updated on each successful authentication).

### SlotAllocation

Tracks assembly slot assignments with full reassignment history:

| Field | Type | Notes |
|-------|------|-------|
| `slot_number` | VARCHAR(32) | e.g. "A1", "B2" |
| `position` | INTEGER | Numeric position within group |
| `group_id` | VARCHAR(64) | Grouping identifier for related slots |
| `is_active` | BOOLEAN | Only one active allocation per blade at any time |
| `previous_slot_number` | VARCHAR(32) | Captured automatically on reassignment |
| `unbalance_value` | NUMERIC(12,6) | Measured unbalance |
| `is_balanced` | BOOLEAN | Balancing outcome |
| `balancing_remarks` | TEXT | |

### BatchGroup

Stores metadata associated with a batch number, populated automatically or via the batch-lookup API. Used to auto-fill blade fields when a known batch number is entered at registration.

| Field | Type | Notes |
|-------|------|-------|
| `batch_number` | VARCHAR(64) UNIQUE | |
| `work_order_number` | VARCHAR(64) | Inherited from first blade in batch |
| `part_number` | VARCHAR(64) | |
| `engine_number` | VARCHAR(64) | |
| `nomenclature` | VARCHAR(128) | |
| `created_at` | TIMESTAMP | |

Batch size is capped at **90 blades per batch number** (enforced at the API layer, constant `BATCH_MAX_BLADES = 90` in `endpoints/blades.py`).

### WorkflowLog (Immutable Audit Trail)

| Field | Type | Notes |
|-------|------|-------|
| `blade_id` | UUID FK | |
| `from_status` | ENUM | NULL on initial transition |
| `to_status` | ENUM | |
| `action_by_id` | UUID FK → users | |
| `station_id` | UUID FK → stations | |
| `remarks` | TEXT | |
| `timestamp` | TIMESTAMP | |
| `metadata_` | JSONB | Arbitrary context (batch info, rejection details, etc.) |

### Report (Async Generated Reports)

| Field | Type | Notes |
|-------|------|-------|
| `report_type` | ENUM | `PDF`, `EXCEL` |
| `status` | ENUM | `PENDING`, `GENERATING`, `READY`, `FAILED` |
| `file_path` | VARCHAR(1024) | `/app/reports/xxx.xlsx` |
| `file_size_bytes` | BIGINT | Set when generation completes |
| `filter_params` | JSONB | Query params used for generation |
| `error_message` | TEXT | Populated on `FAILED` status |
| `completed_at` | TIMESTAMP | |

### Notification (Real-Time Push)

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | UUID FK | NULL = broadcast to all |
| `blade_id` | UUID FK | |
| `notification_type` | ENUM | BLADE_RECEIVED, SLOT_PENDING, BALANCING_DONE, BLADE_REJECTED, VERIFICATION_PENDING, SYSTEM, WORKFLOW_UPDATED, GENERAL |
| `is_read` | BOOLEAN | |
| `read_at` | TIMESTAMP | |
| `expires_at` | TIMESTAMP | Optional TTL; expired notifications hidden from unread list |
| `metadata_` | JSONB | Arbitrary payload (e.g. previous status, slot number) |

### AuditLog (HTTP & Business Action Trail)

Dual-purpose audit table capturing both HTTP traffic and domain events:

```json
{
  "method": "POST",
  "path": "/api/v1/blades/abc/send-to-assembly",
  "status_code": 200,
  "ip_address": "10.0.1.45",
  "duration_ms": 42,
  "action": "blade.send_to_assembly",
  "resource_type": "Blade",
  "resource_id": "abc-uuid",
  "changes": {"status": {"old": "MEASUREMENTS_RECORDED", "new": "SENT_TO_ASSEMBLY"}}
}
```

### Attachment (File Storage Metadata)

Files stored on disk under `/app/uploads/attachments/{blade_id}/{sanitized_filename}`.  
OCR scan images stored under `/app/uploads/ocr_scans/`.

| Field | Type | Notes |
|-------|------|-------|
| `filename` | VARCHAR(255) | Server-side sanitized name |
| `original_filename` | VARCHAR(255) | User-provided name |
| `file_path` | VARCHAR(1024) | Absolute path on server |
| `mime_type` | VARCHAR(128) | Validated via python-magic |
| `attachment_type` | ENUM | `IMAGE`, `DOCUMENT`, `OCR_SCAN` |

---

## 5. Blade Workflow State Machine

Defined in `backend/app/workflows/state_machine.py`.

### States

```
CREATED → OH_INSPECTION → MEASUREMENTS_RECORDED → SENT_TO_ASSEMBLY
                                                        │
                                              SLOT_ASSIGNED
                                                        │
                                           BALANCING_IN_PROGRESS
                                                        │
                                           BALANCING_COMPLETED ──────────────┐
                                                        │                    │
                                              RETURNED_TO_OH                 │
                                                        │                    │
                                           FINAL_VERIFICATION                │
                                                        │                    │
                                               COMPLETED ◄───────────────────┘

Any rejectable state → REJECTED → (SUPER_ADMIN) → REOPENED → OH_INSPECTION
                                                           → SENT_TO_ASSEMBLY
Any active state → ON_HOLD → resumes to OH_INSPECTION or MEASUREMENTS_RECORDED
```

### Allowed Transitions Matrix

| From | To | Actor | Notes |
|------|----|-------|-------|
| CREATED | OH_INSPECTION | System | Auto on create |
| OH_INSPECTION | MEASUREMENTS_RECORDED | OH_OPERATOR | Auto on first measurement |
| OH_INSPECTION | REJECTED | Any operator | |
| OH_INSPECTION | ON_HOLD | Any operator | |
| MEASUREMENTS_RECORDED | SENT_TO_ASSEMBLY | OH_OPERATOR | Batches only if batch_number set |
| MEASUREMENTS_RECORDED | REJECTED | Any operator | |
| MEASUREMENTS_RECORDED | ON_HOLD | Any operator | |
| SENT_TO_ASSEMBLY | SLOT_ASSIGNED | ASSEMBLY_OPERATOR | |
| SLOT_ASSIGNED | BALANCING_IN_PROGRESS | ASSEMBLY_OPERATOR | |
| BALANCING_IN_PROGRESS | BALANCING_COMPLETED | ASSEMBLY_OPERATOR | |
| BALANCING_COMPLETED | RETURNED_TO_OH | ASSEMBLY_OPERATOR | |
| BALANCING_COMPLETED | COMPLETED | ASSEMBLY_OPERATOR | Skip OH return if applicable |
| RETURNED_TO_OH | FINAL_VERIFICATION | OH_OPERATOR | |
| RETURNED_TO_OH | COMPLETED | OH_OPERATOR | Direct completion |
| FINAL_VERIFICATION | COMPLETED | OH_OPERATOR | |
| REJECTED | REOPENED | SUPER_ADMIN | |
| REOPENED | OH_INSPECTION | System | |
| REOPENED | SENT_TO_ASSEMBLY | OH_OPERATOR | If already measured |
| ON_HOLD | OH_INSPECTION | Any operator | Resume target depends on prior state |
| ON_HOLD | MEASUREMENTS_RECORDED | Any operator | |

### WorkflowEngine

```python
engine = WorkflowEngine(db)
await engine.transition(blade, to_status=BladeStatus.SENT_TO_ASSEMBLY, user=current_user)
# Validates transition is in ALLOWED_TRANSITIONS
# Persists WorkflowLog entry with metadata_
# Fires notification events
# Raises WorkflowTransitionError on invalid transition
```

---

## 6. API Reference

Base path: `/api/v1`

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Returns `access_token` + `refresh_token` |
| POST | `/auth/refresh` | Exchange refresh token for new access token |
| GET | `/auth/me` | Current user profile |
| POST | `/auth/logout` | Blacklist current JWT in Redis |

### Blades

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/blades/` | OH_OPERATOR | Register new blade |
| GET | `/blades/` | Any | Paginated list with filters (see below) |
| GET | `/blades/{id}` | Any | Full blade detail |
| PUT | `/blades/{id}` | OH_OPERATOR | Update metadata |
| DELETE | `/blades/{id}` | OH_OPERATOR / SUPER_ADMIN | Delete blade (see deletion rules) |
| GET | `/blades/rejection-reasons/` | Any | List active rejection reason options |
| GET | `/blades/batch-lookup` | Any | Fetch BatchGroup metadata by batch number |
| POST | `/blades/batch-groups` | OH_OPERATOR | Create or update a BatchGroup record |
| GET | `/blades/{id}/qr` | Any | Generate QR code data for blade |
| POST | `/blades/{id}/send-to-assembly` | OH_OPERATOR | Transition to SENT_TO_ASSEMBLY |
| POST | `/blades/{id}/return-to-oh` | ASSEMBLY_OPERATOR | Transition to RETURNED_TO_OH |
| POST | `/blades/{id}/complete` | OH_OPERATOR / ASSEMBLY_OPERATOR | Transition to COMPLETED |
| POST | `/blades/{id}/reject` | Any operator | Reject with reason |
| POST | `/blades/{id}/reopen` | SUPER_ADMIN | Reopen rejected blade |
| POST | `/blades/{id}/hold` | Any operator | Place on hold |
| GET | `/blades/{id}/history` | Any | Workflow log entries |
| POST | `/blades/{id}/attachments` | Any | Upload file attachment |
| GET | `/blades/{id}/attachments` | Any | List attachments |
| POST | `/blades/{id}/attach-ocr-scan` | OH_OPERATOR | Attach a previously scanned OCR image |

#### Blade List Filters

```
GET /blades/?page=1&page_size=20
  &status=OH_INSPECTION                    # single status
  &blade_statuses=OH_INSPECTION,SLOT_ASSIGNED  # multiple statuses (comma-separated)
  &blade_type=LPTR
  &batch_number=B2026-01
  &sort_by=created_at                      # field to sort on
  &sort_desc=true                          # descending order
```

#### Blade Deletion Rules

- `SUPER_ADMIN` can delete any blade regardless of status.
- `OH_OPERATOR` can only delete blades in statuses they own (e.g. `CREATED`, `OH_INSPECTION`) — not blades that have progressed to assembly.
- Deletion is a **hard delete** (row removed), not a soft delete via `deleted_at`. Use with caution; `WorkflowLog` entries for the blade are cascade-deleted.

### Measurements

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/blades/{id}/measurements` | OH_OPERATOR | Record measurement; auto-transitions blade to MEASUREMENTS_RECORDED |
| GET | `/blades/{id}/measurements` | Any | Measurement history |
| GET | `/measurements/{id}` | Any | Single measurement |
| PUT | `/measurements/{id}` | OH_OPERATOR | Update (pre-approval only) |
| POST | `/measurements/{id}/approve` | QA_VIEWER | QA sign-off |

### Slots

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/slots/assign` | ASSEMBLY_OPERATOR | Assign blade to slot |
| GET | `/slots/` | Any | List allocations |
| GET | `/slots/{id}` | Any | Allocation detail |
| PUT | `/slots/{id}` | ASSEMBLY_OPERATOR | Update balancing data |

### Reports

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/reports/` | Any | Request async generation |
| GET | `/reports/` | Any | List reports |
| GET | `/reports/{id}` | Any | Status + metadata |
| GET | `/reports/{id}/download` | Any | StreamingResponse download |

### Other Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| GET `/workflows/history` | Any | Cross-blade workflow events |
| GET `/workflows/dashboard` | Any | Summary statistics |
| GET/POST `/notifications/` | Authenticated | Unread list, mark-read |
| WS `/notifications/ws` | Authenticated | Real-time notification stream |
| WS `/weighing/ws` | OH_OPERATOR | Live scale data stream |
| POST `/dti/push` | Internal (localhost) | Receive DTI reading from bridge script |
| WS `/dti/ws` | OH_OPERATOR | Live DTI height-position readings stream |
| POST `/ocr/scan` | OH_OPERATOR | Scan blade markings image |
| POST `/ocr/verify-numbers` | OH_OPERATOR | Compare OCR result vs manual entry |
| GET/POST `/stations/` | Any/Admin | Station management |
| GET/POST `/batches/` | ASSEMBLY_OPERATOR | Batch event tracking |
| GET `/audit-logs/` | SUPER_ADMIN | Full HTTP + domain audit trail |
| GET `/health` | Public | Liveness check |

### Pagination Envelope

All list endpoints use:

```json
{
  "items": [...],
  "total": 142,
  "page": 1,
  "page_size": 20,
  "pages": 8
}
```

---

## 7. Authentication & RBAC

### JWT Token Structure

```json
{
  "sub": "user-uuid",
  "email": "operator@example.com",
  "roles": ["OH_OPERATOR"],
  "iat": 1718000000,
  "exp": 1718001800,
  "type": "access",
  "jti": "unique-token-id"
}
```

- Access tokens expire in 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- Refresh tokens expire in 7 days (configurable via `REFRESH_TOKEN_EXPIRE_DAYS`)
- Logout blacklists the `jti` in Redis; all middleware checks the blacklist on every request
- `last_login` on the `users` row is updated on each successful `/auth/login`

### RBAC Enforcement

Roles are checked at the endpoint level:

```python
@router.post("/{blade_id}/send-to-assembly")
@require_roles("OH_OPERATOR", "SUPER_ADMIN")
async def send_to_assembly(blade_id: UUID, current_user = Depends(get_current_user)):
    ...
```

SUPER_ADMIN bypasses most role checks and has exclusive access to user management, audit logs, and reopening rejected blades.

---

## 8. Real-Time & Async Processing

### WebSocket Notifications

`NotificationManager` (in-memory) holds a mapping of `user_id → List[WebSocket]`.

```
Client opens WebSocket: /api/v1/notifications/ws?token=<JWT>
→ Server authenticates token
→ Server registers connection in ConnectionManager
→ On any event (blade status change, report ready, etc.):
    NotificationService.create_notification()
    → Persists Notification to DB (survives server restart)
    → ConnectionManager.send_to_user(user_id, payload)
    → Client receives JSON push

On server restart: in-flight WebSocket connections drop.
Clients must reconnect and poll GET /notifications/ for missed messages.
```

### Celery Task Queue

Used exclusively for report generation (CPU/IO-intensive):

```
POST /reports/ → create Report(status=PENDING) → enqueue task
Celery worker:
  → Report(status=GENERATING)
  → Fetch blade/measurement/slot/workflow data
  → ReportGenerator.generate_*() with optional blade_type filter
  → Write file to /app/reports/
  → Report(status=READY, file_path=..., file_size_bytes=..., completed_at=...)
  → Push SYSTEM notification to requesting user
  
On failure:
  → Report(status=FAILED, error_message=...)
  → No notification (client must poll or re-request)
```

Queues: `reports` (report generation), `celery` (default).  
Worker concurrency: 2.  
Max tasks per child: 50 (memory protection against leak accumulation).

---

## 9. Hardware Integration

Three physical instruments feed live readings directly into the measurement form via standalone bridge scripts running on the Windows workstation. Each bridge follows the same pattern: read from serial/USB → POST to backend HTTP endpoint → backend broadcasts over WebSocket → browser auto-fills form field.

```
Instrument              Bridge script           Backend push endpoint     WebSocket endpoint
──────────────────────  ──────────────────────  ────────────────────────  ─────────────────────
Weighing Scale          weighing_bridge.py      POST /weighing/push       WS /weighing/ws
DTI Gauge               dti_bridge.py           POST /dti/push            WS /dti/ws
OCR Camera              ocr_camera_bridge.py*   POST /ocr/scan/blade-serial  (HTTP response)
```

\* OCR camera bridge is described below; it calls the existing HTTP endpoint directly (no separate WebSocket needed because OCR results are one-shot).

None of these scripts are part of the Docker Compose stack. Each runs on the workstation physically connected to the respective instrument.

---

### 9.1 Weighing Scale (scripts/weighing_bridge.py)

Reads blade weight from a digital weighing scale over RS-232/USB and forwards readings to the backend, where they are broadcast to all open browser tabs.

**Hardware interface:**

| Parameter | Value |
|-----------|-------|
| Interface | RS-232 (DB-9) or USB-to-serial adapter |
| Baud rate | 9600 (auto-detected; tries 4800, 2400, 19200, 38400) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None |
| Default port | COM6 |
| Data format | ASCII, e.g. `0450.25\r\n` (grams) |

**Data flow:**

```
Scale → RS-232 → weighing_bridge.py
  → POST /api/v1/weighing/push  {"value": 450.25}
  → backend _broadcast() → all WS /weighing/ws subscribers
  → browser auto-fills weight_grams field
```

**Push payload:**
```json
{"value": 450.25}
```

**WebSocket message to browser:**
```json
{"type": "weight", "value": 450.25}
```

The bridge handles serial port auto-discovery, reconnection on disconnect, and duplicate-reading suppression (unchanged readings are not re-posted).

---

### 9.2 DTI Gauge (scripts/dti_bridge.py)

Reads height-position measurements (H1 … Hn) from a Dial Test Indicator gauge over RS-232. The bridge cycles through positions automatically: the operator moves the probe tip to each position and presses the gauge's DATA/SEND button; the bridge assigns each incoming reading to the next position in sequence and broadcasts it.

**Hardware interface:**

| Parameter | Value |
|-----------|-------|
| Interface | RS-232 (DB-9) or USB-to-serial adapter |
| Baud rate | 9600 (auto-detected) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | None (hardware flow on some Mitutoyo models) |
| Default port | COM7 |
| Data format | ASCII, e.g. `+012.345\r\n` (signed mm, 3 d.p.) |

**Compatible gauges:**

- Mitutoyo 543 series (absolute digimatic indicator)
- Mitutoyo 293 series (micrometer with SPC output)
- Mahr MarCator 1086 R / 810 SW
- Sylvac S_Dial Work / Smart
- Any gauge producing a plain ASCII numeric reading per line

**Data flow:**

```
DTI Gauge → RS-232 → dti_bridge.py (cycles H1 → H2 → H3 → H4)
  → POST /api/v1/dti/push  {"position": "H1", "value": 12.345}
  → backend _broadcast() → all WS /dti/ws subscribers
  → browser auto-fills height_data.H1 field
```

**Push payload:**
```json
{"position": "H1", "value": 12.345}
```

**WebSocket message to browser:**
```json
{"type": "dti", "position": "H1", "value": 12.345}
```

**Command-line usage:**
```bash
# Default: COM7, positions H1-H4
python dti_bridge.py

# Custom port and 5-position sequence
python dti_bridge.py --port COM4 --positions H1 H2 H3 H4 H5

# Remote server
python dti_bridge.py --port COM7 --server https://192.168.1.50
```

---

### 9.3 OCR Camera System (scripts/ocr_camera_bridge.py)

The OCR camera captures blade markings (serial number, melt/heat number, part number stamps) and submits the image to the backend OCR pipeline for extraction and cross-check against manually entered values.

**Hardware interface:**

| Parameter | Value |
|-----------|-------|
| Interface | USB Video Class (UVC) — plug-and-play on Windows 10/11 |
| Alternatively | GigE / USB3 Vision industrial camera via OpenCV |
| Resolution | Minimum 4 MP recommended for small etched markings |
| Lighting | Integrated ring light or external coaxial illumination |
| Trigger | Software trigger via OpenCV `VideoCapture.read()` or hardware trigger via GPIO |

**Protocol: USB/UVC direct capture (recommended)**

The bridge uses OpenCV (`cv2.VideoCapture`) to grab a frame from the camera, saves it to a JPEG in memory, and POSTs it to the backend OCR endpoint. No separate serial connection is required.

**Data flow:**

```
Camera (USB/UVC) → OpenCV VideoCapture → ocr_camera_bridge.py
  → POST /api/v1/ocr/scan/blade-serial  (multipart image)
  → OCR provider extracts serial_number + confidence
  → Response returned to operator UI
  → POST /api/v1/ocr/verify-numbers  (manual vs OCR comparison)
  → Sets blade.ocr_mismatch_flag if discrepancy detected
  → OCR scan image saved to /app/uploads/ocr_scans/
```

**Protocol: GigE Vision / network camera (alternative)**

For industrial cameras with a network interface:
```
Camera (GigE) → LAN → ocr_camera_bridge.py (aravis / harvesters library)
  → Same POST to /api/v1/ocr/scan/* as above
```

**Required Python packages (camera bridge only):**
```
opencv-python>=4.9.0    # UVC capture + image encode
requests                # HTTP POST to backend
```

For GigE Vision cameras add: `harvesters` (or `aravis` bindings).

---

## 10. OCR Integration

### Provider Registry (backend/app/ocr/registry.py)

Three providers available via `OCR_PROVIDER` environment variable:

| Provider | Description | Dependencies | Default? |
|----------|-------------|-------------|---------|
| `mock` | Returns stub data; for dev/test | None | No |
| `tesseract` | Traditional OCR via pytesseract | `tesseract-ocr` system package | No |
| `paddleocr` | Deep learning OCR | `paddlepaddle`, `paddleocr` | **Yes** |

> **Note:** The default provider in `config.py` is `paddleocr`. On servers without GPU or PaddleOCR system dependencies, explicitly set `OCR_PROVIDER=mock` for development and `OCR_PROVIDER=tesseract` as a lightweight production alternative.

### Flow

```
POST /ocr/scan  (multipart: image file)
→ OCRRegistry.get_provider(OCR_PROVIDER).scan(image_bytes)
→ Returns {serial_number, melt_number, confidence}

POST /ocr/verify-numbers  (manual_serial, manual_melt, ocr_serial, ocr_melt)
→ Compare strings
→ Set blade.ocr_mismatch_flag + blade.ocr_mismatch_notes if mismatch detected
→ Return verification result

POST /blades/{id}/attach-ocr-scan
→ Associates a previously scanned image file with the blade as an OCR_SCAN attachment
→ Stores under /app/uploads/ocr_scans/
```

---

## 11. Report Generation

### Supported Formats

| Format | Library | Use Case |
|--------|---------|----------|
| Excel (.xlsx) | openpyxl | Data export, further analysis |
| PDF | ReportLab / WeasyPrint | Print-quality traceability reports |

### Report Filters (stored in `filter_params` JSONB)

```json
{
  "blade_ids": ["uuid1", "uuid2"],
  "status": "COMPLETED",
  "blade_type": "LPTR",
  "date_from": "2026-01-01",
  "date_to": "2026-06-30",
  "batch_number": "B2026-01"
}
```

Reports include: blade identity (including nomenclature, engine hours, component hours), all measurements (initial/interim/final), slot allocations, balancing data, full workflow history, rejection details (if any).

---

## 12. IRS (Inspection Record Sheet) Format

The Inspection Record Sheet is the official per-blade compliance document produced at the end of the OH inspection stage. It is generated as a PDF (printed and signed by the inspector) or Excel (retained in the digital archive). The IRS number uniquely identifies each inspection event.

### IRS Document Number

```
IRS-{WORK_ORDER}-{SERIAL_NUMBER}-{YYYYMMDD}

Example: IRS-45786-SN010001-20260618
```

### IRS Data Sections

#### Section A — Blade Identity

| Field | Source | Notes |
|-------|--------|-------|
| Work Order No. | `blade.work_order_number` | MRO work order |
| Shop Order No. | `blade.shop_order_number` | Internal shop tracking number |
| Part Number | `blade.part_number` | Drawing/part number e.g. 104.04.02.020 |
| Nomenclature | `blade.nomenclature` | Human-readable name e.g. "HP Turbine Blade Stage 1" |
| Serial Number | `blade.serial_number` | Physical blade identifier |
| Melt / Heat Number | `blade.melt_number` | Material batch traceability |
| Engine No. | `blade.engine_number` | Parent engine identifier |
| Blade Type | `blade.blade_type` | `LPTR` or `HPTR` |
| Engine Hours | `blade.engine_hours` | Total engine hours at removal |
| Component Hours | `blade.component_hours` | Blade individual hours at removal |
| Batch Number | `blade.batch_number` | Assembly batch grouping key |
| Inspection Station | `blade.current_station_id → station.name` | OH station name |

#### Section B — OCR Verification

| Field | Source | Notes |
|-------|--------|-------|
| OCR Serial No. (extracted) | `blade.ocr_serial_number` | Extracted by OCR provider |
| OCR Melt No. (extracted) | `blade.ocr_melt_number` | Extracted by OCR provider |
| OCR Provider | Attachment metadata | `mock` / `tesseract` / `paddleocr` |
| Confidence Score | OCR result | 0.0 – 1.0 |
| Mismatch Flag | `blade.ocr_mismatch_flag` | `YES` if OCR disagrees with manual entry |
| Mismatch Notes | `blade.ocr_mismatch_notes` | Inspector explanation of any discrepancy |
| Scan Image Reference | `attachment.id` where `attachment_type=OCR_SCAN` | Stored at `/app/uploads/ocr_scans/` |

#### Section C — Weighing Machine Readings

| Field | Source | Notes |
|-------|--------|-------|
| Gross Weight | `measurement.weight_grams` | Blade weight in grams |
| Static Moment | `measurement.static_moment_gcm` | Auto-calculated: weight × 1.57 × 20 (g·cm) |
| Measurement Type | `measurement.measurement_type` | `INITIAL` / `INTERIM` / `FINAL` |
| Recorded By | `measurement.measured_by_id → user.full_name` | OH operator |
| Recorded At | `measurement.measured_at` | Timestamp |
| Station | `measurement.station_id → station.name` | Weighing station |
| Scale Calibration Ref. | Free-text remarks field | Entered by operator; references the scale's calibration certificate |

**Static moment formula:**
```
Static Moment (g·cm) = Weight (g) × Moment Arm (cm)
                     = weight_grams × 1.57 × 20
```

#### Section D — DTI (Dial Test Indicator) Readings

| Field | Source | Notes |
|-------|--------|-------|
| H1 reading | `measurement.height_data["H1"]` | Tip height at position 1 (mm) |
| H2 reading | `measurement.height_data["H2"]` | Tip height at position 2 (mm) |
| H3 reading | `measurement.height_data["H3"]` | Tip height at position 3 (mm) |
| H4 reading | `measurement.height_data["H4"]` | Tip height at position 4 (mm) |
| … Hn | `measurement.height_data["Hn"]` | Additional positions as required |
| DTI Gauge Calibration Ref. | Free-text remarks field | References the gauge's calibration certificate |

Height data is stored as a JSONB map `{"H1": 12.34, "H2": 11.95, …}` in the `measurements` table. Position keys must match the pattern `H<n>` (H1, H2, H3, …). Readings are captured live from the DTI gauge via `dti_bridge.py` and auto-populated into the measurement form.

#### Section E — Rocking & Creep Values

| Field | Source | Notes |
|-------|--------|-------|
| Slot Number | `slot_allocation.slot_number` | Assigned by Assembly; must be present before entry |
| Rocking Value | `measurement.rocking_value` | Required for all blade types |
| Creep Value | `measurement.creep_value` | LPTR blades only; mandatory if blade_type = LPTR |

Rules enforced at the API layer:
- **LPTR**: both `rocking_value` AND `creep_value` are mandatory.
- **HPTR**: only `rocking_value` is mandatory; `creep_value` must be null.

#### Section F — Inspection Results & QA Sign-off

| Field | Source | Notes |
|-------|--------|-------|
| Overall Result | Derived from `blade.status` | `PASS` if `MEASUREMENTS_RECORDED` or later active state; `FAIL` if `REJECTED` |
| Rejection Reason | `blade.rejection_reason_id → rejection_reason.description` | Populated only on FAIL |
| Rejection Notes | `blade.rejection_notes` | Inspector's narrative |
| Inspector Remarks | `measurement.notes` | Free-text field on the measurement record |
| Approved By | `measurement.approved_by_id → user.full_name` | QA sign-off name |
| Approval Date | `measurement.approved_at` | QA sign-off timestamp |
| Approval Status | `measurement.is_approved` | `APPROVED` / `PENDING` |

#### Section G — Workflow Timeline

Sourced from `WorkflowLog` entries for the blade, ordered by timestamp:

| Column | Notes |
|--------|-------|
| Status (from → to) | State transition labels |
| Station | Station where action occurred |
| Performed By | User who triggered the transition |
| Timestamp | UTC datetime |
| Remarks | Optional operator note |

### IRS in the Report Generator

When generating a blade PDF or Excel report, the IRS structure above is mapped to the output:

- **PDF**: Printed in sections A–G on consecutive pages. Each section has a title bar, tabular data, and a signature/approval footer.
- **Excel**: One sheet per section (Sheet 1 = Identity, Sheet 2 = Measurements, Sheet 3 = DTI/Rocking/Creep, Sheet 4 = Workflow History).

The filter `filter_params.serial_number` or `filter_params.status` on the report generation request controls which blades' IRS records are included in a batch report.

---

## 13. Infrastructure & Deployment

### Docker Compose Services

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `postgres` | postgres:15-alpine | internal | UTF-8 locale; volume: postgres_data |
| `redis` | redis:7-alpine | internal | Password auth required; max 256 MB LRU; volume: redis_data |
| `backend` | custom (Dockerfile) | 8000 (internal) | 4 Gunicorn workers |
| `celery_worker` | same as backend | — | Same image, different CMD |
| `frontend` | custom (Dockerfile) | 80 (via nginx) | Static SPA |
| `nginx` | nginx:1.27-alpine | 80, 443 | Entry point |

All services share a named Docker network `blade_rocking_net`.

### Volumes

```
postgres_data   — persistent PostgreSQL data
redis_data      — persistent Redis AOF/RDB
./uploads       — file attachments (bind mount)
./reports       — generated reports (bind mount)
./logs          — structured logs (bind mount)
./ssl           — TLS certificates (production)
```

### CI/CD (GitHub Actions)

Four jobs on push to `main`:

1. **backend-test** — pytest with Postgres 15 + Redis 7 services, 70% coverage gate
2. **frontend-test** — TypeScript type-check, ESLint, Vite production build
3. **docker-build** — build + push images to GHCR (main branch only)
4. **deploy** (on `v*` tags) — SSH to server, pull images, `alembic upgrade head`, rolling restart

### Database Migrations

```bash
# New migration (after model change)
alembic revision --autogenerate -m "describe_change"

# Apply
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

Existing migrations:
- `20260529_initial_schema` — bootstrap
- `20260601_add_blade_type` — `blade_type` ENUM (LPTR/HPTR)
- `20260616_add_sent_to_assembly_batch_event` — batch event tracking

---

## 14. Security

### Controls

| Control | Implementation |
|---------|----------------|
| Password hashing | bcrypt, cost factor 12 |
| JWT signing | PyJWT 2.x, HS256, 64-char random `SECRET_KEY` |
| Token revocation | Redis blacklist keyed on JWT `jti` |
| Transport security | NGINX TLS (configurable; self-signed in dev) |
| CORS | Origin whitelist via `CORS_ORIGINS` env var |
| Rate limiting | SlowAPI middleware (10 req/min default per IP) |
| Input validation | Pydantic v2 strict schemas on all endpoints |
| SQL injection | SQLAlchemy parameterized queries only |
| Audit trail | Every HTTP request + domain event logged to `audit_logs` |
| Soft deletes | Users and blades (non-deleted path) use `deleted_at` timestamp |
| Hard deletes | Blade deletion via DELETE endpoint removes rows permanently |
| File upload | MIME-type validation via python-magic; size cap via `MAX_FILE_SIZE_MB` |

---

## 15. Testing

### Structure

```
backend/app/tests/
├── conftest.py               # Async fixtures: db, test_user, test_blade, client
├── api/
│   ├── test_auth.py          # Login, refresh, logout, /me
│   ├── test_blades.py        # CRUD, workflow transitions, RBAC
│   └── test_rbac.py          # Cross-role access matrix
└── unit/
    └── test_workflow.py      # State machine transitions (no DB)
```

### Running Tests

```bash
# Full suite with coverage (70% minimum)
pytest app/tests/ -v --cov=app --cov-fail-under=70

# Unit only (fast, no DB)
pytest app/tests/unit/ -v

# API integration
pytest app/tests/api/ -v

# Single test
pytest app/tests/api/test_blades.py::test_send_to_assembly -v
```

### Key Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db` | function | In-process async DB session |
| `client` | function | AsyncTestClient with test DB |
| `test_user` | function | OH_OPERATOR user |
| `admin_user` | function | SUPER_ADMIN user |
| `test_blade` | function | Blade in OH_INSPECTION status |
| `fake_redis` | session | fakeredis instance (no real Redis needed) |

---

## 16. Configuration Reference

### Required Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://blade_user:password@postgres:5432/blade_rocking
POSTGRES_DB=blade_rocking
POSTGRES_USER=blade_user
POSTGRES_PASSWORD=<strong-password>

# Security (generate: python3 -c "import secrets; print(secrets.token_hex(32))")
SECRET_KEY=<64-char-hex>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Redis / Celery — Redis requires password auth in all environments
REDIS_URL=redis://:password@redis:6379/0
REDIS_PASSWORD=<strong-password>
CELERY_BROKER_URL=redis://:password@redis:6379/1
CELERY_RESULT_BACKEND=redis://:password@redis:6379/2

# CORS (comma-separated list for production)
CORS_ORIGINS=["https://your-domain.internal"]
```

### Optional Environment Variables

```bash
# OCR backend: mock | tesseract | paddleocr  (default: paddleocr)
# Set to mock for dev machines without PaddleOCR installed
OCR_PROVIDER=mock

# File storage
UPLOAD_DIR=/app/uploads
REPORTS_DIR=/app/reports
MAX_FILE_SIZE_MB=10

# Email notifications (leave blank to disable; smtp_enabled property checks all fields)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_TLS=true                   # Use TLS when connecting to SMTP server
EMAILS_FROM_EMAIL=noreply@example.com

# Observability
LOG_LEVEL=INFO
LOG_FORMAT=json
ENABLE_METRICS=false            # Prometheus endpoint at /metrics

# Runtime
ENVIRONMENT=dev|staging|prod
DEBUG=false
APP_NAME=Blade Rocking & Creep Test Management System
APP_VERSION=1.0.0
```

### Make Targets

```bash
make install          # Install backend + frontend deps
make dev-backend      # FastAPI with hot-reload (port 8000)
make dev-frontend     # Vite dev server (port 5173)
make migrate          # alembic upgrade head
make seed             # Load development seed data
make test             # Full pytest suite
make test-coverage    # Pytest with HTML coverage report
make lint             # ruff + mypy
make up               # docker-compose up -d
make down             # docker-compose down
make logs             # Tail all container logs
make shell-backend    # bash into backend container
make shell-db         # psql into postgres container
```
