# Technical Design Document
## Blade Rocking & Creep Test Management System

**Version:** 1.5  
**Owner:** Meridian Data Labs  
**Contact:** amit@meridiandatalabs.com

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Directory Structure](#3-directory-structure)
4. [Data Model](#4-data-model)
5. [Blade Workflow State Machine](#5-blade-workflow-state-machine)
6. [Assembly Verification & Set-Making](#6-assembly-verification--set-making)
7. [API Reference](#7-api-reference)
8. [Authentication & RBAC](#8-authentication--rbac)
9. [Real-Time & Async Processing](#9-real-time--async-processing)
10. [Hardware Integration](#10-hardware-integration)
11. [OCR Integration](#11-ocr-integration)
12. [Report Generation](#12-report-generation)
13. [IRS (Inspection Record Sheet) Format](#13-irs-inspection-record-sheet-format)
14. [Infrastructure & Deployment](#14-infrastructure--deployment)
15. [Security](#15-security)
16. [Testing](#16-testing)
17. [Configuration Reference](#17-configuration-reference)

---

## 1. System Overview

The Blade Rocking & Creep Test Management System tracks turbine blades through their complete overhaul (OH) lifecycle: incoming inspection, dimensional measurement (rocking/creep tests), assembly slot allocation, dynamic balancing, and final quality verification before return to service.

### Physical Deployment

The system runs across **two independent workstations** connected over a LAN. There is no dedicated central server.

| Station | Location | Role |
|---------|----------|------|
| **OH Station** | 701 Hanger — Measurement Station | Blade inspection, OCR, weighing, DTI, IRS generation |
| **Assembly Station** | 720 Hanger — Set-Making & Balancing | Receipt verification, set-making (HAL algo), balancing, slot allocation |

The OH PC hosts the shared PostgreSQL database. The Assembly PC application connects to it over the LAN. Both stations continue to function independently if the network is temporarily unavailable (read-only degrades gracefully; writes queue).

### Business Problem

Turbine blades undergo periodic overhaul cycles. Each blade must be individually measured (weight, static moment, rocking value, creep value, height positions), grouped into compatible sets for a given engine, allocated to assembly slots, balanced, and re-verified before dispatch. Paper-based tracking and spreadsheets create traceability gaps and audit failures. This system replaces that process with a digital workflow that enforces sequencing, captures measurements directly from instruments, and produces exportable traceability reports.

### Core Capabilities

- Blade registration and identity verification (serial number, melt number, part number)
- Multi-stage dimensional measurement capture with automated static moment calculation
- Batch-level tracking: **180 blades per batch** (90 LPTR + 90 HPTR) moving between OH and Assembly
- OCR scan of blade markings (serial, melt number) with mismatch detection — dual-language PP-OCRv4 engine (English + Cyrillic); optional Luxonis OAK-1 industrial camera bridge on OH station
- Live weight capture from Adam Equipment iScale i-04 (0.1 g) via serial bridge
- Live DTI readings from Sylvac BT gauge (0.001 mm) via serial bridge
- Assembly verification loop: receive batch → scan/validate vs OH records → accept / modify / reject per blade
- Set-making with HAL (Heavy-light Alternating Layout) descending-sort algorithm, 2–3 balancing iterations
- Slot allocation and dynamic balancing record-keeping
- Rejection workflow with reason classification and SUPER_ADMIN-controlled reopening
- Async PDF/Excel IRS report generation for compliance and shipping packages
- Real-time WebSocket notifications across operator workstations
- QR code generation per blade for mobile scanning
- Full immutable audit trail at both HTTP and domain-event levels

---

## 2. Architecture

### Physical Topology

```
  ┌──────────────────────────────────────────────────────────────┐
  │  701 Hanger — OH Measurement Station                         │
  │                                                              │
  │  Hardware: iScale i-04 · Sylvac BT DTI · Luxonis OAK-1 (opt)│
  │                                                              │
  │  ┌───────────────┐   ┌─────────────────────────────────┐    │
  │  │  React 18 SPA │   │  FastAPI + Celery + NGINX        │    │
  │  │  OH operator  │   │                                  │    │
  │  │  interface    │   │  ┌────────────┐  ┌───────────┐  │    │
  │  └───────────────┘   │  │ PostgreSQL │  │  Redis 7  │  │    │
  │                      │  │  (shared)  │  │  (local)  │  │    │
  │  Bridge scripts:     │  └────────────┘  └───────────┘  │    │
  │  weighing_bridge.py  └─────────────────────────────────┘    │
  │  dti_bridge.py                                               │
  │  oak1_camera_service.py  (if OAK-1 attached)                │
  └──────────────────────────────┬───────────────────────────────┘
                                 │
                          LAN (TCP/IP)
                     bidirectional REST + WS
                         /api/v1/sync/*
                                 │
  ┌──────────────────────────────┴───────────────────────────────┐
  │  720 Hanger — Assembly Set-Making & Balancing Station        │
  │                                                              │
  │  Hardware: OCR Camera (USB) · QR Scanner (HID) · Balancing  │
  │                                                              │
  │  ┌───────────────┐   ┌───────────────────────────────────┐  │
  │  │  React 18 SPA │   │  FastAPI (lightweight)            │  │
  │  │  Assembly op. │   │  DATABASE_URL → OH PC PostgreSQL  │  │
  │  │  interface    │   │  OH_SYNC_URL → https://<OH-PC-IP> │  │
  │  └───────────────┘   └───────────────────────────────────┘  │
  │                                                              │
  │  Bridge scripts (target OH PC API):                          │
  │  weighing_bridge.py  --server https://<OH-PC-IP>            │
  │  dti_bridge.py       --server https://<OH-PC-IP>            │
  └──────────────────────────────────────────────────────────────┘
```

**Single shared database:** PostgreSQL runs only on the OH PC. The Assembly PC's backend points its `DATABASE_URL` to `postgresql+asyncpg://blade_user:pass@<OH-PC-LAN-IP>:5432/blade_rocking`. No replication is required — both stations write directly to the same Postgres instance.

### Software Stack

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
   │  (OH PC only)    │  │  Celery broker   │  │  (openpyxl /      │
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
| OCR | PP-OCRv4 dual-language (English + Cyrillic, local models) | Blade marking extraction; OAK-1 companion service provides frames |
| Hardware | pyserial | iScale i-04 weighing + Sylvac BT DTI serial bridges |

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
│   │   │   ├── router.py            # Top-level router; 16 sub-routers
│   │   │   └── endpoints/           # 16 endpoint modules:
│   │   │       ├── assembly.py      #   Assembly verification + set-making
│   │   │       ├── audit_logs.py    #   Audit trail (SUPER_ADMIN)
│   │   │       ├── auth.py          #   Login, refresh, logout
│   │   │       ├── batches.py       #   Batch lifecycle + HAL slot assignment
│   │   │       ├── blades.py        #   Blade CRUD + workflow transitions
│   │   │       ├── dti.py           #   DTI gauge WebSocket + push
│   │   │       ├── measurements.py  #   Measurement CRUD + QA approval
│   │   │       ├── notifications.py #   Notification list + WebSocket
│   │   │       ├── ocr.py           #   OCR scan + verify
│   │   │       ├── reports.py       #   Async report generation
│   │   │       ├── slots.py         #   Slot allocation + balancing
│   │   │       ├── stations.py      #   Station management
│   │   │       ├── sync.py          #   LAN sync (OH PC → Assembly)
│   │   │       ├── users.py         #   User management (SUPER_ADMIN)
│   │   │       └── weighing.py      #   Weighing scale WebSocket + push
│   │   ├── repositories/            # Data access layer (5 files)
│   │   ├── services/                # Business logic
│   │   │   ├── blade_service.py     #   Blade lifecycle
│   │   │   ├── assembly_service.py  #   Assembly verification logic
│   │   │   └── weighing_service.py  #   Weighing scale data
│   │   ├── workflows/
│   │   │   └── state_machine.py     # ALLOWED_TRANSITIONS + WorkflowEngine
│   │   ├── notifications/           # WebSocket manager + persistence
│   │   ├── ocr/                     # Pluggable OCR provider registry
│   │   │   └── models/ppocrv4/      # Bundled PP-OCRv4 weights (det, cls, rec_en, rec_ru ~26 MB)
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
│   │   ├── routes/
│   │   │   └── index.tsx            # All 18 application routes
│   │   ├── components/              # Reusable UI (Radix UI + Tailwind)
│   │   ├── pages/                   # Route-level views (18 pages)
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── services/                # Axios API client + React Query (incl. oak1Camera.ts)
│   │   ├── stores/                  # Zustand state
│   │   └── types/                   # TypeScript type definitions
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── scripts/
│   ├── deploy.sh                    # Production deployment helper
│   ├── dti_bridge.py               # DTI gauge RS-232 → API bridge
│   ├── manage_batches.py            # Batch management CLI
│   ├── oak1_camera_service.py      # OAK-1 camera companion service (Flask, port 8089)
│   ├── oak1_ocr_test.py            # OAK-1 OCR validation/test script
│   ├── oak1_requirements.txt       # OAK-1 venv deps (depthai, flask, flask-cors, cv2)
│   ├── reset_and_seed_full.py       # Full DB reset + re-seed
│   ├── seed_data.py                 # Dev data seeder
│   ├── seed_demo_data.py            # Demo data for presentations
│   └── weighing_bridge.py          # Weighing scale RS-232 → API bridge
├── nginx/
│   └── nginx.conf
├── docker-compose.yml               # Unified single-machine deployment
├── docker-compose.oh.yml            # OH Station (701 Hanger) only
├── docker-compose.assembly.yml      # Assembly Station (720 Hanger) only
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

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `serial_number` | VARCHAR(64) UNIQUE | Physical blade identifier |
| `melt_number` | VARCHAR(64) | Material traceability |
| `work_order_number` | VARCHAR(64) | MRO work order |
| `shop_order_number` | VARCHAR(64) | Internal shop order |
| `part_number` | VARCHAR(64) | Drawing/part number |
| `engine_number` | VARCHAR(64) | Parent engine |
| `engine_hours` | VARCHAR(64) | Engine total hours at removal |
| `component_hours` | VARCHAR(64) | Blade individual hours at removal |
| `batch_number` | VARCHAR(64) | Grouping key for assembly batches |
| `blade_type` | ENUM | `LPTR` or `HPTR` |
| `status` | ENUM | 15 states (see state machine) |
| `current_station_id` | UUID FK → stations | |
| `created_by_id` | UUID FK → users | |
| `assigned_to_id` | UUID FK → users | |
| `ocr_serial_number` | VARCHAR(64) | OCR-extracted serial |
| `ocr_melt_number` | VARCHAR(64) | OCR-extracted melt number |
| `ocr_mismatch_flag` | BOOLEAN | Set when OCR disagrees with manual entry |
| `ocr_mismatch_notes` | TEXT | Explanation of the mismatch |
| `deleted_at` | TIMESTAMP | Soft delete |

### Measurement

| Field | Type | Notes |
|-------|------|-------|
| `measurement_type` | ENUM | `INITIAL`, `INTERIM`, `FINAL` |
| `weight_grams` | NUMERIC(12,4) | |
| `static_moment_gcm` | NUMERIC(12,4) | Auto-calculated: weight × 1.57 × 20 |
| `rocking_value` | NUMERIC(12,6) | Required for all blade types |
| `creep_value` | NUMERIC(12,6) | LPTR blades only; must be null for HPTR |
| `station_id` | UUID FK → stations | Station where measured |
| `is_approved` | BOOLEAN | QA sign-off |
| `approved_by_id` | UUID FK → users | |
| `approved_at` | TIMESTAMP | |

**Auto-transition:** Recording a measurement on a blade in `OH_INSPECTION` automatically transitions it to `MEASUREMENTS_RECORDED`.

**Type rules enforced at the API layer:**
- `LPTR`: both `rocking_value` AND `creep_value` are mandatory.
- `HPTR`: only `rocking_value` is mandatory; `creep_value` must be null.

### Users & RBAC

Four built-in roles:

| Role | Capabilities |
|------|-------------|
| `SUPER_ADMIN` | Full access, user management, reopen rejected blades |
| `OH_OPERATOR` | Create blades, record measurements, send to assembly |
| `ASSEMBLY_OPERATOR` | Assign slots, update balancing, return to OH |
| `QA_VIEWER` | Read-only access across all entities |

User fields include `last_login` timestamp (updated on each successful authentication).

### AssemblyBladeRecord

Tracks per-blade verification state during the Assembly receipt process. Created when a batch is received at 720 Hanger. One record per blade per batch.

| Field | Type | Notes |
|-------|------|-------|
| `blade_id` | UUID FK | |
| `batch_number` | VARCHAR(64) | |
| `status` | ENUM | `AssemblyVerificationStatus`: PENDING, ACCEPTED, MODIFIED, REJECTED |
| `qr_scan_result` | VARCHAR(64) | Serial number scanned by QR gun |
| `ocr_blade_number` | VARCHAR(64) | Blade number from OCR |
| `assembly_weight` | NUMERIC | Weight measured at Assembly |
| `oh_weight` | NUMERIC | OH FINAL weight (copied at receipt time) |
| `weight_delta` | NUMERIC | `assembly_weight - oh_weight` |
| `verification_notes` | TEXT | Operator notes on discrepancies |
| `verified_by_id` | UUID FK → users | |
| `verified_at` | TIMESTAMP | |

`MODIFIED` status is set when accept is called with field overrides that differ from OH values.

### SlotAllocation

| Field | Type | Notes |
|-------|------|-------|
| `slot_number` | VARCHAR(32) | e.g. "1" – "80" (integer slot around disk) |
| `position` | INTEGER | Numeric position within group |
| `group_id` | VARCHAR(64) | Grouping identifier for related slots |
| `is_active` | BOOLEAN | Only one active allocation per blade at any time |
| `previous_slot_number` | VARCHAR(32) | Captured automatically on reassignment |
| `unbalance_value` | NUMERIC(12,6) | Measured unbalance |
| `is_balanced` | BOOLEAN | Balancing outcome |
| `balancing_remarks` | TEXT | |

### BatchGroup

Stores metadata associated with a batch number. Used to auto-fill blade fields when a known batch number is entered at registration.

| Field | Type | Notes |
|-------|------|-------|
| `batch_number` | VARCHAR(64) UNIQUE | |
| `work_order_number` | VARCHAR(64) | Inherited from first blade in batch |
| `part_number` | VARCHAR(64) | |
| `engine_number` | VARCHAR(64) | |
| `created_at` | TIMESTAMP | |

**Batch size cap:** 90 LPTR + 90 HPTR = **180 blades total per batch number**. Enforced at the API layer via `BATCH_MAX_PER_TYPE = 90` in `endpoints/blades.py`. Per-type counts are validated independently.

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

Files stored at `/app/uploads/attachments/{blade_id}/{sanitized_filename}`.  
OCR scan images stored at `/app/uploads/ocr_scans/`.

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
                                             ASSEMBLY_RECEIVED       ← POST /assembly/batches/.../receive
                                                        │
                                             ASSEMBLY_VERIFIED       ← POST /assembly/blades/.../accept
                                                        │
                                              SLOT_ASSIGNED          ← POST /batches/.../assign-slot (HAL)
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

ASSEMBLY_RECEIVED → REJECTED   (via POST /assembly/blades/.../reject)

Any other active state → REJECTED → (SUPER_ADMIN) → REOPENED → OH_INSPECTION
                                                              → SENT_TO_ASSEMBLY
```

**14 total states:** CREATED, OH_INSPECTION, MEASUREMENTS_RECORDED, SENT_TO_ASSEMBLY, ASSEMBLY_RECEIVED, ASSEMBLY_VERIFIED, SLOT_ASSIGNED, BALANCING_IN_PROGRESS, BALANCING_COMPLETED, RETURNED_TO_OH, FINAL_VERIFICATION, COMPLETED, REJECTED, REOPENED.

### Allowed Transitions Matrix

| From | To | Actor | Notes |
|------|----|-------|-------|
| CREATED | OH_INSPECTION | System | Auto on create |
| OH_INSPECTION | MEASUREMENTS_RECORDED | OH_OPERATOR | Auto on first measurement |
| OH_INSPECTION | REJECTED | Any operator | |
| MEASUREMENTS_RECORDED | SENT_TO_ASSEMBLY | OH_OPERATOR | |
| MEASUREMENTS_RECORDED | REJECTED | Any operator | |
| SENT_TO_ASSEMBLY | ASSEMBLY_RECEIVED | System | Via POST /assembly/batches/.../receive |
| ASSEMBLY_RECEIVED | ASSEMBLY_VERIFIED | ASSEMBLY_OPERATOR | Via POST /assembly/blades/.../accept |
| ASSEMBLY_RECEIVED | REJECTED | ASSEMBLY_OPERATOR | Via POST /assembly/blades/.../reject |
| ASSEMBLY_VERIFIED | SLOT_ASSIGNED | ASSEMBLY_OPERATOR | Via HAL batch assign-slot |
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

## 6. Assembly Verification & Set-Making

This section describes the end-to-end workflow that the **Assembly Station (720 Hanger)** runs after receiving a batch from OH. Implemented in `backend/app/api/v1/endpoints/assembly.py` and `backend/app/services/assembly_service.py`.

### Step 1 — Receive Batch

```
POST /assembly/batches/{batch_number}/receive
→ All blades in batch: SENT_TO_ASSEMBLY → ASSEMBLY_RECEIVED
→ Creates AssemblyBladeRecord per blade (copies OH FINAL measurements)
→ Creates BatchEvent(event_type=RECEIVED_BY_ASSEMBLY)
→ Notifies OH_OPERATORs

GET /assembly/batches/{batch_number}/progress
→ Returns { total_expected, assembly_received, assembly_verified, rejected }
   total_expected falls back to 180 if no receipt record exists
```

### Step 2 — Verify Each Blade (assessment only — no status change)

The operator QR-scans each blade, enters Assembly-side measurements, and calls verify. **This step does NOT change `blade.status`** — it only updates the `AssemblyBladeRecord` and returns a suggested action.

```
POST /assembly/blades/{blade_id}/verify?batch_number=BXXX
body: { assembly_weight, qr_scan_result, ocr_blade_number }

AssemblyService.verify_blade():
  1. Load AssemblyBladeRecord (contains oh_weight copied at receipt)
  2. Compare assembly_weight vs oh_weight: tolerance ±0.5 g
  3. Check qr_scan_result matches blade.serial_number
  4. Check ocr_blade_number matches blade.serial_number
  5. Compute weight_delta; set verification_notes for any out-of-tolerance field
  6. Return suggested_action:
       "REJECT"  — identity mismatch (QR or OCR serial doesn't match)
       "ACCEPT"  — all values within tolerance
       "REVIEW"  — within tolerance but discrepancies warrant human sign-off
  Blade remains ASSEMBLY_RECEIVED until accept or reject is called.
```

### Step 3 — Accept or Reject (status-changing)

```
POST /assembly/blades/{blade_id}/accept?batch_number=BXXX
  → body: optional field overrides { assembly_weight }
  → AssemblyBladeRecord.status → ACCEPTED (or MODIFIED if overrides differ from OH)
  → blade.status: ASSEMBLY_RECEIVED → ASSEMBLY_VERIFIED
  → Note: station_id is NOT recorded on this workflow log entry (known limitation)

POST /assembly/blades/{blade_id}/reject?batch_number=BXXX
  → body: { notes }
  → AssemblyBladeRecord.status → REJECTED
  → blade.status: ASSEMBLY_RECEIVED → REJECTED
  → Creates BatchEvent(event_type=REJECTED)
  → Notifies OH_OPERATORs
  → Note: station_id is NOT recorded on this workflow log entry (known limitation)

POST /batches/{batch_number}/accept   (bulk accept all remaining ASSEMBLY_RECEIVED blades)
POST /batches/{batch_number}/reject   (bulk reject entire batch)
POST /batches/{batch_number}/modify   (batch-level field modifications, creates MODIFIED events)
```

### Step 4 — Start Set-Making (gate check only)

```
POST /assembly/batches/{batch_number}/start-setmaking
→ Validates: assembly_verified count >= total_expected (ALL blades must be verified)
→ Returns SetMakingResponse { status: "INITIATED" }
→ Does NOT run HAL or create slots — that is a separate call.
   The operator then calls POST /batches/{batch_number}/assign-slot to run HAL.
```

### Step 5 — HAL Slot Assignment

**Endpoint:** `POST /batches/{batch_number}/assign-slot`  
**Implemented in:** `backend/app/api/v1/endpoints/batches.py`

**Gate check:** The batch must have its latest `BatchEvent.event_type` in `{ACCEPTED, MODIFIED}`. Any other event type raises HTTP 422.

**Eligible blade statuses:** `SENT_TO_ASSEMBLY`, `ASSEMBLY_RECEIVED`, `ASSEMBLY_VERIFIED` — all three are valid inputs to the HAL step.

**HAL Algorithm (Heavy-light Alternating Layout):**

Purpose: distribute blades around the disc so heavy blades sit opposite lighter blades, minimising first-order imbalance before dynamic balancing.

```python
# Inputs (request body):
#   imbalance_slot: int   REQUIRED — 1 to total_slots (no default; omitting → HTTP 422)
#   total_slots:    int   default 80

# 1. Uses INITIAL measurement type, static_moment_gcm column
sorted_blades = sorted(blades, key=lambda b: -sm_map.get(str(b.id), 0))

# 2. Interleave: heavy first half + reversed light second half
half = len(sorted_blades) // 2
interleaved = sorted_blades[:half] + list(reversed(sorted_blades[half:]))
# Result: alternates heavy–light–heavy–light around disc circumference

# 3. Place starting from the known imbalance position
# K = imbalance_slot, N = total_slots
for i, blade in enumerate(interleaved):
    computed_slot = str(((K - 1 + i) % N) + 1)
    create SlotAllocation(blade_id=blade.id, slot_number=computed_slot)
    transition blade → SLOT_ASSIGNED
```

`imbalance_slot` is the disc position the balancing machine identified as the current heavy spot in a previous run. Placing the heaviest blade there creates the opposing force on the next run.

### Assembly Endpoint Summary

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/assembly/batches/{batch_number}/receive` | ASSEMBLY_OPERATOR | Receive batch; transitions all blades to ASSEMBLY_RECEIVED |
| GET | `/assembly/batches/{batch_number}/receipt` | Any | Receipt details |
| GET | `/assembly/batches/{batch_number}/progress` | Any | Verification progress counts |
| GET | `/assembly/batches/{batch_number}/blades` | Any | Blades with AssemblyVerificationStatus |
| POST | `/assembly/blades/{blade_id}/verify` | ASSEMBLY_OPERATOR | Assess (no status change) — `?batch_number=` query param |
| POST | `/assembly/blades/{blade_id}/accept` | ASSEMBLY_OPERATOR | Accept → ASSEMBLY_VERIFIED — `?batch_number=` query param |
| POST | `/assembly/blades/{blade_id}/reject` | ASSEMBLY_OPERATOR | Reject → REJECTED — `?batch_number=` query param |
| POST | `/assembly/batches/{batch_number}/start-setmaking` | ASSEMBLY_OPERATOR | Gate check; returns INITIATED |

---

## 7. API Reference

Base path: `/api/v1`  
**16 sub-routers** registered in `backend/app/api/v1/router.py`.

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
| GET | `/blades/` | Any | Paginated list (see filters below) |
| GET | `/blades/{id}` | Any | Full blade detail |
| PUT | `/blades/{id}` | OH_OPERATOR | Update metadata |
| DELETE | `/blades/{id}` | OH_OPERATOR / SUPER_ADMIN | Hard delete (see deletion rules) |
| GET | `/blades/rejection-reasons/` | Any | List active rejection reason options |
| GET | `/blades/batch-lookup` | Any | Fetch BatchGroup metadata by batch number |
| POST | `/blades/batch-groups` | OH_OPERATOR | Create or update a BatchGroup record |
| GET | `/blades/{id}/qr` | Any | Generate QR code data for blade |
| POST | `/blades/{id}/send-to-assembly` | OH_OPERATOR | Transition to SENT_TO_ASSEMBLY |
| POST | `/blades/{id}/return-to-oh` | ASSEMBLY_OPERATOR | Transition to RETURNED_TO_OH |
| POST | `/blades/{id}/complete` | OH_OPERATOR / ASSEMBLY_OPERATOR | Transition to COMPLETED |
| POST | `/blades/{id}/reject` | Any operator | Reject with reason |
| POST | `/blades/{id}/reopen` | SUPER_ADMIN | Reopen rejected blade |
| GET | `/blades/{id}/history` | Any | Workflow log entries |
| POST | `/blades/{id}/attachments` | Any | Upload file attachment |
| GET | `/blades/{id}/attachments` | Any | List attachments |
| POST | `/blades/{id}/attach-ocr-scan` | OH_OPERATOR | Attach a previously scanned OCR image |

**Blade List Filters:**
```
GET /blades/?page=1&page_size=20
  &status=OH_INSPECTION
  &blade_statuses=OH_INSPECTION,SLOT_ASSIGNED   # comma-separated multi-status
  &blade_type=LPTR
  &batch_number=B2026-01
  &sort_by=created_at
  &sort_desc=true
```

**Blade Deletion Rules:**
- `SUPER_ADMIN`: can delete any blade regardless of status.
- `OH_OPERATOR`: can only delete blades in their own statuses (`CREATED`, `OH_INSPECTION`).
- Deletion is a **hard delete** — rows are removed and `WorkflowLog` entries cascade-delete.

### Measurements

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/blades/{id}/measurements` | OH_OPERATOR | Record; auto-transitions to MEASUREMENTS_RECORDED |
| GET | `/blades/{id}/measurements` | Any | Measurement history |
| GET | `/measurements/{id}` | Any | Single measurement |
| PUT | `/measurements/{id}` | OH_OPERATOR | Update (pre-approval only) |
| POST | `/measurements/{id}/approve` | QA_VIEWER | QA sign-off |

### Slots

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/slots/assign` | ASSEMBLY_OPERATOR | Assign blade to a slot |
| POST | `/slots/reassign` | ASSEMBLY_OPERATOR | Reassign blade to a new slot (updates previous_slot_number) |
| PUT | `/slots/{slot_id}/balancing` | ASSEMBLY_OPERATOR | Record balancing result |
| GET | `/slots/` | Any | List active slot allocations (paginated, filterable) |
| GET | `/slots/blade/{blade_id}` | Any | Get current active slot for a blade |

### Batches

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/batches/` | Any | List all batches with current status |
| GET | `/batches/{batch_number}` | Any | Batch detail + full event history |
| POST | `/batches/{batch_number}/send-to-assembly` | OH_OPERATOR | Bulk-send all eligible blades in batch |
| POST | `/batches/{batch_number}/assign-slot` | ASSEMBLY_OPERATOR | Run HAL algorithm + assign all slots |
| GET | `/batches/{batch_number}/rocking-creep` | Any | Rocking/creep values for all blades in batch |
| POST | `/batches/{batch_number}/receive` | ASSEMBLY_OPERATOR | Mark batch received |
| POST | `/batches/{batch_number}/accept` | ASSEMBLY_OPERATOR | Bulk-accept remaining unverified blades |
| POST | `/batches/{batch_number}/modify` | ASSEMBLY_OPERATOR | Apply blade-level field modifications |
| POST | `/batches/{batch_number}/events` | ASSEMBLY_OPERATOR | Log a raw batch event |

### Assembly (Section 6 for detail)

See [Section 6](#6-assembly-verification--set-making) for the full assembly verification workflow.

> Note: the per-blade endpoints (`verify`, `accept`, `reject`) take `batch_number` as a **query parameter**, not a path segment: `POST /assembly/blades/{blade_id}/verify?batch_number=BXXX`

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/assembly/batches/{batch_number}/receive` | ASSEMBLY_OPERATOR | Receive batch; transitions all blades to ASSEMBLY_RECEIVED |
| GET | `/assembly/batches/{batch_number}/receipt` | Any | Receipt details |
| GET | `/assembly/batches/{batch_number}/progress` | Any | Verification progress counts |
| GET | `/assembly/batches/{batch_number}/blades` | Any | Blades with AssemblyVerificationStatus |
| POST | `/assembly/blades/{blade_id}/verify?batch_number=` | ASSEMBLY_OPERATOR | Assess vs OH — no BladeStatus change |
| POST | `/assembly/blades/{blade_id}/accept?batch_number=` | ASSEMBLY_OPERATOR | Accept → ASSEMBLY_VERIFIED |
| POST | `/assembly/blades/{blade_id}/reject?batch_number=` | ASSEMBLY_OPERATOR | Reject → REJECTED |
| POST | `/assembly/batches/{batch_number}/start-setmaking` | ASSEMBLY_OPERATOR | Gate check; HAL runs via `/batches/.../assign-slot` |

### Reports

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/reports/` | Any | Request async generation |
| GET | `/reports/` | Any | List reports |
| GET | `/reports/{id}` | Any | Status + metadata |
| GET | `/reports/{id}/download` | Any | StreamingResponse download |

### DTI Gauge

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/dti/push` | Internal (bridge script) | Receive height-position reading |
| GET | `/dti/positions` | OH_OPERATOR | Get current position count (how many H positions) |
| POST | `/dti/positions` | OH_OPERATOR | Set position count for next blade |
| POST | `/dti/reset` | OH_OPERATOR | Force cycle reset to H1 |
| WS | `/dti/ws?station=1` | OH_OPERATOR | Stream live DTI readings to browser |

DTI endpoints support a `?station=1` or `?station=2` parameter for two-station deployments.

### Weighing Scale

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/weighing/push` | Internal (bridge script) | Receive weight reading |
| WS | `/weighing/ws` | OH_OPERATOR | Stream live weight readings to browser |

### Sync (LAN Data Export)

The `/sync` router exposes read-only endpoints on the OH PC that the Assembly station calls to pull a snapshot of blade data over the LAN. All three endpoints require `ASSEMBLY_OPERATOR`, `OH_OPERATOR`, or `SUPER_ADMIN`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sync/status` | Station identity: `{ station_type, station_name, api_version, synced_at, status }` |
| GET | `/sync/blades` | Blade snapshot. Filters: `?batch_number=`, `?status=`. Response: `OHSyncResponse` with flat field `weight` (not `weight_grams`) |
| GET | `/sync/batches/{batch_number}` | Single batch snapshot |

`station_type` and `station_name` in `/sync/status` fall back to hardcoded strings if `STATION_TYPE` / `STATION_NAME` env vars are not set.

### Other Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| GET `/workflows/history` | Any | Cross-blade workflow events |
| GET `/workflows/dashboard` | Any | Summary statistics |
| GET/POST `/notifications/` | Authenticated | Unread list, mark-read |
| WS `/notifications/ws` | Authenticated | Real-time notification stream |
| POST `/ocr/scan` | OH_OPERATOR | Scan blade markings image |
| POST `/ocr/verify-numbers` | OH_OPERATOR | Compare OCR vs manual entry |
| GET/POST `/stations/` | Any/Admin | Station management |
| GET `/audit-logs/` | SUPER_ADMIN | Full HTTP + domain audit trail |
| GET `/health` | Public | Liveness check |

### Pagination Envelope

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

## 8. Authentication & RBAC

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
- Refresh tokens expire in 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`)
- Logout blacklists the `jti` in Redis; all middleware checks the blacklist on every request
- `last_login` on the `users` row is updated on each successful `/auth/login`

### RBAC Enforcement

```python
@router.post("/{blade_id}/send-to-assembly")
@require_roles("OH_OPERATOR", "SUPER_ADMIN")
async def send_to_assembly(blade_id: UUID, current_user = Depends(get_current_user)):
    ...
```

SUPER_ADMIN bypasses most role checks and has exclusive access to user management, audit logs, and reopening rejected blades.

---

## 9. Real-Time & Async Processing

### WebSocket Notifications

`NotificationManager` (in-memory) holds `user_id → List[WebSocket]`.

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

Used exclusively for report generation:

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
```

Queues: `reports`, `celery`.  Worker concurrency: 2.  Max tasks per child: 50.

---

## 10. Hardware Integration

Physical instruments connect to the Windows workstation at each hangar station via RS-232, USB-to-serial adapter, or USB3.  Three bridge scripts forward data to the backend.

```
Instrument          Model                    Bridge script            Push / stream
──────────────────  ───────────────────────  ───────────────────────  ────────────────────────
Weighing Scale      iScale i-04, 0.1 g       weighing_bridge.py       POST /weighing/push
DTI Gauge           Sylvac BT, 0.001 mm      dti_bridge.py            POST /dti/push
OAK-1 Camera        Luxonis OAK-1 (IMX378)   oak1_camera_service.py   GET /snapshot, GET /stream
QR Scanner          USB HID barcode gun      (keyboard emulation)     Browser reads directly
Balancing Machine   Turbine disc             Manual entry UI          POST /batches/assign-slot
```

Bridge scripts are **not** part of the Docker Compose stack. Run each on the workstation physically connected to the instrument.
The OAK-1 service is optional — both stations work without it; the browser webcam is the fallback capture path.

---

### 10.1 Weighing Scale (scripts/weighing_bridge.py)

**Model: Adam Equipment iScale i-04, resolution 0.1 g**

| Parameter | Value |
|-----------|-------|
| Default port | COM6 |
| Baud rates tried | 9600, 4800, 2400, 19200, 38400 (auto-detect) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Data format | ASCII, e.g. `0450.25\r\n` (grams) |

**Data flow:**

```
Scale → RS-232 → weighing_bridge.py
  → POST /api/v1/weighing/push  {"value": 450.25}
  → backend broadcast → all WS /weighing/ws subscribers
  → browser auto-fills weight_grams field in measurement form
```

**WebSocket message to browser:**
```json
{"type": "weight", "value": 450.25}
```

CLI usage:
```bash
python weighing_bridge.py --port COM6
python weighing_bridge.py --port COM6 --server https://192.168.1.50
```

---

### 10.2 DTI Gauge (scripts/dti_bridge.py)

**Model: Sylvac BT, resolution 0.001 mm (Bluetooth RS-232 adapter)**

| Parameter | Value |
|-----------|-------|
| Default port | COM1 |
| Baud rates tried | 9600, 4800, 2400, 19200, 38400 (auto-detect) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Data format | ASCII, e.g. `+012.345\r\n` (signed mm, 3 d.p.) |

**Position cycling:** The bridge advances positions using the `next_position` field returned in each `/dti/push` response — no manual configuration needed. The position count is set by the frontend via `POST /dti/positions` when rows are added/removed from the measurement form. The bridge does NOT call `GET /dti/positions` itself; the cycle length is maintained entirely server-side.

> **Note:** The `--positions` CLI argument appears in the script's docstring but is **not implemented** in argparse. Do not rely on it.

Use `POST /dti/reset?station=1` to force cycle back to H1 when starting a new blade — the frontend calls this automatically on new blade entry.

**Debounce:** duplicate readings within 1.5 seconds are suppressed.

**SSL:** bridge uses `session.verify = False` (self-signed cert expected on both stations).

**Server check:** bridge polls `GET /health` before opening the serial port; retries every 5 s until the server responds.

**Compatible gauges:**
- Sylvac BT (this deployment)
- Mitutoyo 543 series (absolute digimatic indicator)
- Mahr MarCator 1086 R / 810 SW
- Any gauge producing a plain ASCII numeric reading per line

**Data flow:**

```
DTI Gauge → RS-232 → dti_bridge.py
  → POST /api/v1/dti/push  {"station": "1", "position": "H1", "value": 12.345}
  → response: {"ok": true, "next_position": "H2", "position_count": 4, ...}
  → backend broadcasts to all WS /dti/ws?station=1 subscribers
  → browser auto-fills the active Rocking/Creep cell in RockingCreepPage
```

**WebSocket messages sent to browser:**

| Message | When |
|---------|------|
| `{"type": "status", "status": "connected", "station": "1"}` | On connect |
| `{"type": "dti", "position": "H1", "value": 12.345}` | Each new reading |
| `{"type": "ping"}` | Every 30 s (keepalive) |

On reconnect, the server immediately replays all readings captured for the current blade on that station (from `_cycle_readings` in-memory buffer), so the form is not blank after a page refresh or WS disconnect.

CLI usage:
```bash
python dti_bridge.py                                          # COM1, station 1
python dti_bridge.py --port COM4 --station 2                 # COM4, station 2
python dti_bridge.py --port COM1 --server https://192.168.1.50
python dti_bridge.py --debug                                  # verbose serial logging
```

---

---

### 10.3 OAK-1 Camera (scripts/oak1_camera_service.py)

**Model: Luxonis OAK-1 (Sony IMX378, 12 MP RGB sensor)**

The OAK-1 is not a UVC webcam — the browser's `getUserMedia()` cannot see it. A standalone Flask companion service keeps the DepthAI pipeline open and serves frames over plain localhost HTTP on port **8089**, which the frontend fetches directly. This service never talks to the backend; captured frames are handed to the existing OCR upload path as a JPEG blob.

#### Camera pipeline

The OAK-1 runs **two simultaneous outputs** so preview smoothness and still-capture quality are decoupled:

| Output | Resolution | Usage |
|--------|-----------|-------|
| `preview` | 640 × 360 | Pre-encoded JPEG in a background thread; served zero-cost by `/stream` |
| `video` | 1920 × 1080 | Raw frame held in memory; JPEG-encoded on demand by `/snapshot` |

#### Endpoints

| Endpoint | Returns | Description |
|----------|---------|-------------|
| `GET /health` | `{"connected": bool, "device_id": str\|null}` | Device availability check |
| `GET /snapshot` | JPEG bytes (`image/jpeg`) | Latest full-res frame; HTTP 503 if no device |
| `GET /stream` | `multipart/x-mixed-replace` MJPEG | Continuous live preview stream |

#### Frontend integration (`frontend/src/services/oak1Camera.ts`)

| Function | Description |
|----------|-------------|
| `checkOak1Health()` | Health probe with 1.5 s timeout; returns `false` if unavailable |
| `captureOak1Snapshot()` | Fetches `/snapshot` as a Blob; throws on failure — callers catch and fall back to webcam |
| `getOak1StreamUrl()` | Returns the `/stream` URL for direct use as `<img src>` |

`BladeEntryPage` and `CameraScanner` call `checkOak1Health()` when the camera modal opens. If the OAK-1 is reachable a **source toggle button** appears in the modal header (Cpu icon = OAK-1 / Video icon = browser webcam). OAK-1 preview renders as an `<img>` element pointed at the MJPEG stream; the browser webcam uses a `<video>` element with `getUserMedia()`. Capture follows the selected source and produces a JPEG blob fed into the existing OCR upload path — the backend sees no difference between sources.

Frontend reads the base URL from `VITE_OAK1_SERVICE_URL` env var (default `http://localhost:8089`).

**Note:** Chromium treats `http://localhost` as a secure-context exception, so HTTPS-page → HTTP-companion mixed content is allowed in Chrome/Edge. This is an intentional shop-floor constraint (known browser on a fixed machine).

#### Configuration

| Parameter | Default | CLI flag |
|-----------|---------|---------|
| Port | 8089 | `--port` |
| CORS origins | `https://localhost`, `http://localhost:3000` | `--frontend-origin` (repeatable) |
| Camera FPS | 30 | — |
| Preview JPEG quality | 80 | — |
| Still JPEG quality | 92 | — |
| Stream delivery FPS | 24 | — |
| depthai version | 2.31.x or 2.32.x | — |

`depthai` is pinned to 2.31.x/2.32.x — this specific OAK-1 unit's onboard USB bootloader firmware was validated against that build only.

#### Auto-reconnect

`Oak1CameraWorker` runs in a background thread with a 5 s retry loop. If the device is unplugged or causes a USB error, the pipeline closes and re-opens automatically. `/health` returns `{"connected": false}` until reconnection.

#### Requirements & installation

Install in a separate venv to avoid dependency conflicts with the main backend:

```bash
cd scripts
python -m venv oak1-venv
oak1-venv\Scriptsctivate          # Windows
pip install -r oak1_requirements.txt  # depthai 2.31/2.32, flask, flask-cors, opencv-python, numpy
```

#### CLI usage

```bash
python oak1_camera_service.py                                      # port 8089, localhost CORS
python oak1_camera_service.py --port 8090
python oak1_camera_service.py --frontend-origin https://192.168.1.50
```


## 11. OCR Integration

### Provider Registry (backend/app/ocr/registry.py)

Three providers available via `OCR_PROVIDER` environment variable:

| Provider | Default? | Dependencies |
|----------|---------|-------------|
| `mock` | No | None — stub data, for dev/test |
| `tesseract` | No | `tesseract-ocr` system package |
| `paddleocr` | **Yes** | `paddlepaddle`, `paddleocr`, `opencv-contrib-python-headless`, `numpy`, `pyzbar` |

> **Note:** Default in `config.py` is `paddleocr`. On machines without PaddleOCR installed, set `OCR_PROVIDER=mock` for dev or `OCR_PROVIDER=tesseract` for lightweight production use.

---

### 11.1 PaddleOCR Provider — Dual-Language Engine (`backend/app/ocr/paddle_provider.py`)

The active OCR implementation is a **dual-language PP-OCRv4 fusion engine** that runs English and Cyrillic recognition in parallel and merges results at the character level. This is designed for blade markings that may contain both Latin alphanumerics (serial numbers, part numbers) and Cyrillic script (melt/heat numbers stamped in Russian manufacturing).

#### Model files

All model weights are **bundled locally** under `backend/app/ocr/models/ppocrv4/` (~26 MB total). No internet download is required at runtime.

| Sub-model | Path | Purpose |
|-----------|------|---------|
| Detection | `models/ppocrv4/det/` | Locate text regions in the image |
| Classification | `models/ppocrv4/cls/` | Correct text line orientation |
| English recognition | `models/ppocrv4/rec_en/` | Recognise Latin + digits + symbols |
| Cyrillic recognition | `models/ppocrv4/rec_ru/` | Recognise Cyrillic script |

Models are loaded once at provider instantiation. `KMP_DUPLICATE_LIB_OK=TRUE` is set to suppress OpenMP conflict aborts on Windows.

#### Image preprocessing pipeline

For each OCR request the provider generates **three preprocessed variants** of the input image and selects the best one:

| Variant | OpenCV transform |
|---------|----------------|
| Grayscale | Convert to gray → CLAHE equalisation |
| Green channel | Extract BGR green channel → CLAHE |
| Red channel | Extract BGR red channel → CLAHE |

CLAHE (Contrast Limited Adaptive Histogram Equalisation) is applied with `clipLimit=3.0, tileGridSize=(8, 8)`. The variant with the **highest score** (detection region count × 100 + average confidence) is passed to the recognition models.

The backend receives the image as raw bytes; preprocessing decodes via `cv2.imdecode(numpy.frombuffer(...), cv2.IMREAD_COLOR)`.

#### Character-level fusion

Both English and Cyrillic recognisers run on the selected preprocessed image. Results are fused **character by character** using deterministic rules:

```
For each character position (aligned by region/line):
  If character is a pure Cyrillic letter  → take Cyrillic reading
  If character is a digit / symbol / Latin → take English reading
  If readings disagree and no clear rule applies → take English reading
```

Character classification uses two pre-defined sets:
- `_PURE_CYRILLIC` — Cyrillic-only Unicode codepoints (А–Я, а–я, Ё, ё, etc.)
- `_INDUSTRIAL_SYMBOLS` — digits, Latin letters, and common stamp characters (`-`, `/`, `\`, space, etc.)

This approach handles markings like `SN-М1034-Б` where the melt number contains Cyrillic suffixes mixed with alphanumeric prefixes.

#### OCR flow

```
Image bytes received at POST /ocr/scan
  → decode BGR frame with cv2
  → generate 3 preprocessed variants
  → score each variant (det_count × 100 + avg_conf)
  → select best variant
  → run English PP-OCRv4 recogniser
  → run Cyrillic PP-OCRv4 recogniser
  → fuse results character-by-character
  → return {serial_number, melt_number, confidence}

POST /ocr/verify-numbers  (manual_serial, manual_melt, ocr_serial, ocr_melt)
  → compare strings
  → set blade.ocr_mismatch_flag + blade.ocr_mismatch_notes on mismatch
  → return verification result

POST /blades/{id}/attach-ocr-scan
  → associate scanned image with blade as OCR_SCAN attachment
  → store under /app/uploads/ocr_scans/
```

#### New backend dependencies (requirements.txt)

```
opencv-contrib-python-headless==4.10.0.84   # image decode + CLAHE preprocessing
numpy>=1.23.5,<2.0.0                         # array bridge between cv2 and PaddleOCR
pyzbar==0.1.9                                # QR/barcode decode fallback
```

---


## 12. Report Generation

### Supported Formats

| Format | Library | Use Case |
|--------|---------|----------|
| Excel (.xlsx) | openpyxl | Data export, further analysis |
| PDF | ReportLab / WeasyPrint | Print-quality traceability reports |

### Report Filters

```json
{
  "blade_ids": ["uuid1", "uuid2"],
  "status": "COMPLETED",
  "blade_type": "LPTR",
  "date_from": "2026-01-01",
  "date_to": "2026-06-30",
  "batch_number": "B2026-01",
  "serial_number": "SN010001"
}
```

### Report Structure

The generator (`backend/app/reports/generator.py`) produces **5 sheets/sections**:

| Sheet | Contents |
|-------|----------|
| 1 — Summary | Serial, melt, status, station, created, updated |
| 2 — Measurements | Type, weight, static moment, rocking, creep, date, station |
| 3 — Slot Allocations | Serial, slot #, position, balanced flag, imbalance value |
| 4 — Workflow History | From/to status, actor, timestamp |
| 5 — Batch Traceability | Batch #, serial, melt, blade type, status, slot, rocking, creep |

A **Dashboard Summary** report (separate type) additionally includes: total blade count, blades by status, blades by station, rejection rate %, average processing hours.

The IRS logical sections (A–G, described in Section 13) map across these 5 sheets.

---

## 13. IRS (Inspection Record Sheet) Format

The Inspection Record Sheet is the official per-blade compliance document produced at the end of the OH inspection stage. It is generated as a PDF (printed and signed by the inspector) or Excel (retained in the digital archive). The IRS number uniquely identifies each inspection event.

### IRS Document Number

```
IRS-{WORK_ORDER}-{SERIAL_NUMBER}-{YYYYMMDD}

Example: IRS-45786-SN010001-20260618
```

### IRS Data Sections

#### Section A — Blade Identity

| Field | Source |
|-------|--------|
| Work Order No. | `blade.work_order_number` |
| Shop Order No. | `blade.shop_order_number` |
| Part Number | `blade.part_number` |
| Serial Number | `blade.serial_number` |
| Melt / Heat Number | `blade.melt_number` |
| Engine No. | `blade.engine_number` |
| Blade Type | `blade.blade_type` |
| Engine Hours | `blade.engine_hours` |
| Component Hours | `blade.component_hours` |
| Batch Number | `blade.batch_number` |
| Inspection Station | `blade.current_station_id → station.name` |

#### Section B — OCR Verification

| Field | Source |
|-------|--------|
| OCR Serial No. (extracted) | `blade.ocr_serial_number` |
| OCR Melt No. (extracted) | `blade.ocr_melt_number` |
| OCR Provider | Attachment metadata |
| Confidence Score | OCR result (0.0 – 1.0) |
| Mismatch Flag | `blade.ocr_mismatch_flag` |
| Mismatch Notes | `blade.ocr_mismatch_notes` |
| Scan Image Reference | `attachment.id` where `attachment_type=OCR_SCAN` |

#### Section C — Weighing Machine Readings

| Field | Source | Notes |
|-------|--------|-------|
| Gross Weight | `measurement.weight_grams` | Blade weight in grams |
| Static Moment | `measurement.static_moment_gcm` | weight × 1.57 × 20 (g·cm) |
| Measurement Type | `measurement.measurement_type` | INITIAL / INTERIM / FINAL |
| Recorded By | `measurement.measured_by_id → user.full_name` | |
| Recorded At | `measurement.measured_at` | |
| Station | `measurement.station_id → station.name` | |
| Scale Calibration Ref. | Free-text `measurement.notes` | |

**Static moment formula:**
```
Static Moment (g·cm) = weight_grams × 1.57 × 20
```

#### Section D — Rocking & Creep Values

| Field | Source | Notes |
|-------|--------|-------|
| Slot Number | `slot_allocation.slot_number` | Assigned by Assembly |
| Rocking Value | `measurement.rocking_value` | All blade types |
| Creep Value | `measurement.creep_value` | LPTR only; null for HPTR |

Rules enforced at the API layer:
- **LPTR**: both `rocking_value` AND `creep_value` are mandatory.
- **HPTR**: only `rocking_value` is mandatory; `creep_value` must be null.

#### Section E — Inspection Results & QA Sign-off

| Field | Source |
|-------|--------|
| Overall Result | Derived: `PASS` if status is active post-inspection; `FAIL` if REJECTED |
| Rejection Notes | `AssemblyBladeRecord.verification_notes` (set via the Assembly reject flow) |
| Inspector Remarks | `measurement.notes` |
| Approved By | `measurement.approved_by_id → user.full_name` |
| Approval Date | `measurement.approved_at` |
| Approval Status | `measurement.is_approved` |

#### Section F — Workflow Timeline

Sourced from `WorkflowLog` entries for the blade, ordered by timestamp:

| Column | Notes |
|--------|-------|
| Status (from → to) | State transition labels |
| Station | Station where action occurred |
| Performed By | User who triggered the transition |
| Timestamp | UTC datetime |
| Remarks | Optional operator note |

---

## 14. Infrastructure & Deployment

### Deployment Modes

Three Docker Compose configurations cover the deployment scenarios:

| File | Use Case | Database |
|------|----------|----------|
| `docker-compose.yml` | Single-machine (dev, testing, all-in-one) | Postgres runs locally |
| `docker-compose.oh.yml` | OH Station (701 Hanger) production | Postgres runs here; exposes `/api/v1/sync/*` to LAN |
| `docker-compose.assembly.yml` | Assembly Station (720 Hanger) production | Connects to OH PC Postgres; sets `STATION_ROLE=ASSEMBLY` and `OH_SYNC_URL` |

For the two-station deployment:
1. Start OH PC with `docker-compose.oh.yml` — this hosts the database
2. Start Assembly PC with `docker-compose.assembly.yml` — set `DATABASE_URL` and `OH_SYNC_URL` to point at OH PC's LAN IP

### Docker Compose Services

| Service | Image | Notes |
|---------|-------|-------|
| `postgres` | postgres:15-alpine | UTF-8 locale; volume: postgres_data; OH PC only |
| `redis` | redis:7-alpine | Password auth required; max 256 MB LRU; volume: redis_data |
| `backend` | custom (Dockerfile) | 4 Gunicorn workers; port 8000 internal |
| `celery_worker` | same as backend | Queues: reports, celery; concurrency: 2 |
| `frontend` | custom (Dockerfile) | Static SPA served via NGINX |
| `nginx` | nginx:1.27-alpine | Entry point; ports 80, 443 |

All services share Docker network `blade_rocking_net`.

### Volumes

```
postgres_data   — persistent PostgreSQL data
redis_data      — persistent Redis AOF/RDB
./uploads       — file attachments + OCR scans (bind mount)
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
alembic revision --autogenerate -m "describe_change"
alembic upgrade head
alembic downgrade -1
```

Existing migrations:
- `20260529_initial_schema` — bootstrap
- `20260601_add_blade_type` — `blade_type` ENUM (LPTR/HPTR)
- `20260616_add_sent_to_assembly_batch_event` — batch event tracking

---

## 15. Security

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
| Soft deletes | Users: `deleted_at` timestamp |
| Hard deletes | Blade DELETE endpoint removes rows permanently |
| File upload | MIME-type validation via python-magic; size cap via `MAX_FILE_SIZE_MB` |

---

## 16. Testing

### Structure

```
backend/app/tests/
├── conftest.py               # Async fixtures: db, test_user, test_blade, client
├── api/
│   ├── test_auth.py
│   ├── test_blades.py
│   └── test_rbac.py
└── unit/
    └── test_workflow.py      # State machine transitions (pure Python, no DB)
```

### Running Tests

```bash
pytest app/tests/ -v --cov=app --cov-fail-under=70   # full suite (70% gate)
pytest app/tests/unit/ -v                              # unit only (fast)
pytest app/tests/api/ -v                               # API integration
pytest app/tests/api/test_blades.py::test_send_to_assembly -v
```

### Key Fixtures

| Fixture | Description |
|---------|-------------|
| `db` | In-process async DB session |
| `client` | AsyncTestClient with test DB |
| `test_user` | OH_OPERATOR user |
| `admin_user` | SUPER_ADMIN user |
| `test_blade` | Blade in OH_INSPECTION status |
| `fake_redis` | fakeredis (no real Redis needed) |

---

## 17. Frontend Routes

Defined in `frontend/src/routes/index.tsx`. Role-based routing enforced client-side; role mismatches redirect to the role's home page.

**Landing page by role:** `SUPER_ADMIN` → `/dashboard`; `QA_VIEWER` → `/qa-dashboard`; all others → `/batch-tracking`.

| Route | Page | Minimum Role |
|-------|------|-------------|
| `/login` | LoginPage | Public |
| `/` | RoleHome (redirect) | Authenticated |
| `/dashboard` | DashboardPage | SUPER_ADMIN |
| `/qa-dashboard` | QaDashboardPage | QA_VIEWER |
| `/blades/new` | BladeEntryPage | OH_OPERATOR |
| `/blades/:id` | BladeDetailPage | Any |
| `/blades/:id/timeline` | WorkflowTimelinePage | Any |
| `/oh-queue` | OHQueuePage | OH_OPERATOR |
| `/assembly-queue` | AssemblyQueuePage | ASSEMBLY_OPERATOR |
| `/slots` | SlotAllocationPage | ASSEMBLY_OPERATOR |
| `/rocking-creep` | RockingCreepPage | OH_OPERATOR |
| `/assembly/verify/:batchNumber` | AssemblyVerificationPage | ASSEMBLY_OPERATOR |
| `/batch-tracking` | BatchTrackingPage | Any |
| `/batches/:batchNumber/modify` | ModifyBatchPage | ASSEMBLY_OPERATOR |
| `/batches/:batchNumber/accept` | AcceptBatchPage | ASSEMBLY_OPERATOR |
| `/reports` | ReportsPage | Any |
| `/users` | UserManagementPage | SUPER_ADMIN |
| `/notifications` | NotificationsPage | Authenticated |
| `/settings` | SettingsPage | Authenticated |

---

## 18. Configuration Reference

### Required Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://blade_user:password@postgres:5432/blade_rocking
POSTGRES_DB=blade_rocking
POSTGRES_USER=blade_user
POSTGRES_PASSWORD=<strong-password>

# Security
SECRET_KEY=<64-char-hex>   # python3 -c "import secrets; print(secrets.token_hex(32))"
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Redis / Celery — Redis requires password auth in all environments
REDIS_URL=redis://:password@redis:6379/0
REDIS_PASSWORD=<strong-password>
CELERY_BROKER_URL=redis://:password@redis:6379/1
CELERY_RESULT_BACKEND=redis://:password@redis:6379/2

# CORS
CORS_ORIGINS=["https://your-domain.internal"]
```

### Optional Environment Variables

```bash
# Two-station deployment (Assembly PC only)
STATION_ROLE=ASSEMBLY          # "OH" or "ASSEMBLY"
STATION_TYPE=ASSEMBLY          # Used in /sync/status response
STATION_NAME="Assembly Station — 720 Hanger"   # Used in /sync/status response
OH_SYNC_URL=https://192.168.1.50

# OCR backend (default: paddleocr — set mock for dev without PaddleOCR installed)
OCR_PROVIDER=mock              # mock | tesseract | paddleocr

# OAK-1 camera companion service (frontend env var, not backend)
# VITE_OAK1_SERVICE_URL=http://localhost:8089   # default; set if service runs on different host/port

# File storage
UPLOAD_DIR=/app/uploads
REPORTS_DIR=/app/reports
MAX_FILE_SIZE_MB=10

# Email notifications (leave blank to disable)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_TLS=true
EMAILS_FROM_EMAIL=noreply@example.com

# Observability
LOG_LEVEL=INFO
LOG_FORMAT=json
ENABLE_METRICS=false           # Prometheus endpoint at /metrics

# Runtime
ENVIRONMENT=dev|staging|prod
DEBUG=false
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
