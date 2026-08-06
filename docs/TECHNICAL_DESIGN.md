# Technical Design Document
## Blade Rocking & Creep Test Management System

**Version:** 1.6  
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
- **Work Order-based tracking:** 90 blades per Work Order (one blade type per WO); 90-row grid entry with autosave, Excel bulk import, and entry-complete gating before OH inspection begins
- OCR scan of blade markings (serial, melt number) with mismatch detection — dual-language PP-OCRv4 engine (English + Cyrillic); optional Luxonis OAK-1 industrial camera bridge on OH station
- Live weight capture from Adam Equipment iScale i-04 (0.1 g) via serial bridge
- Live DTI readings from Sylvac BT gauge (0.001 mm) via serial bridge
- LPTR assembly verification loop: receive WO → scan/validate vs OH records → accept / modify / reject per blade
- HPTR stays at OH station; slots assigned directly by OH_OPERATOR using HPTR HAL (computed client-side)
- Set-making with HAL (Heavy-light Alternating Layout) descending-sort algorithm; LPTR two-stage slot allocation with balancing checks and manual corrections audit trail
- Slot allocation and dynamic balancing record-keeping; LPTR unbalance limit enforced via `LPTR_UNBALANCE_LIMIT_G`
- Rejection workflow with SUPER_ADMIN-controlled reopening
- Async PDF/Excel report generation + 4 synchronous export endpoints (blade list, WO report, HPTR W1/W2 slots, LPTR slots + corrections)
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
| API Gateway | NGINX 1.27 | Rate limiting, static assets (HTTP-only on LAN) |
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
│   │   ├── models/                  # SQLAlchemy ORM entities
│   │   │   ├── work_order.py        #   Work Order header (replaced BatchGroup)
│   │   │   ├── lptr_balancing_check.py  # LPTR stage balancing records
│   │   │   └── enums.py             #   All domain enums (14 BladeStatus values)
│   │   ├── schemas/                 # Pydantic I/O schemas
│   │   │   ├── work_order.py        #   WorkOrder create/row/response schemas
│   │   │   └── lptr_balancing.py    #   LPTR balancing check schemas
│   │   ├── api/v1/
│   │   │   ├── router.py            # Top-level router; 17 sub-routers
│   │   │   └── endpoints/           # 17 endpoint modules:
│   │   │       ├── assembly.py      #   Assembly verification + set-making
│   │   │       ├── audit_logs.py    #   Audit trail (SUPER_ADMIN)
│   │   │       ├── auth.py          #   Login, refresh, logout
│   │   │       ├── blades.py        #   Blade CRUD + workflow transitions
│   │   │       ├── dti.py           #   DTI gauge WebSocket + push
│   │   │       ├── lptr_balancing.py #  LPTR empty-rotor, balancing-check, corrections
│   │   │       ├── measurements.py  #   Measurement CRUD + rocking/creep patch
│   │   │       ├── notifications.py #   Notification list + WebSocket
│   │   │       ├── ocr.py           #   OCR scan + verify
│   │   │       ├── reports.py       #   Async + sync export endpoints
│   │   │       ├── slots.py         #   Slot allocation (role depends on blade_type)
│   │   │       ├── stations.py      #   Station management
│   │   │       ├── sync.py          #   LAN sync (OH PC → Assembly)
│   │   │       ├── users.py         #   User management (SUPER_ADMIN)
│   │   │       ├── weighing.py      #   Weighing scale WebSocket + push
│   │   │       ├── work_orders.py   #   Work Order lifecycle (20 endpoints)
│   │   │       └── workflows.py     #   Workflow history + dashboard stats
│   │   ├── repositories/            # Data access layer (5 files)
│   │   ├── services/                # Business logic
│   │   │   ├── assembly_service.py  #   Assembly verification logic
│   │   │   ├── excel_import.py      #   Excel Work Order bulk-import parser
│   │   │   └── work_order_service.py #  Work Order lifecycle + row autosave
│   │   ├── workflows/
│   │   │   └── state_machine.py     # ALLOWED_TRANSITIONS + EXTRA_TRANSITIONS_BY_TYPE + WorkflowEngine
│   │   ├── notifications/           # WebSocket manager + persistence
│   │   ├── ocr/                     # Pluggable OCR provider registry
│   │   │   └── models/ppocrv4/      # Bundled PP-OCRv4 weights (det, cls, rec_en, rec_ru ~26 MB)
│   │   ├── reports/                 # Excel/PDF generator + Celery tasks
│   │   ├── middleware/              # Audit logging, rate limiting
│   │   └── tests/                   # pytest suite (conftest + 5 test files)
│   ├── alembic/                     # Schema migrations
│   │   └── versions/                # Migration scripts (assembly_workflow, remove_height_dti, drop_nomenclature, …)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/
│   │   │   └── index.tsx            # All 22 application routes (+ redirect aliases)
│   │   ├── components/              # Reusable UI (Radix UI + Tailwind)
│   │   ├── pages/                   # Route-level views (22 pages)
│   │   │   ├── blade-entry/         #   BladeEntryGrid, GridRow, ExcelImportButton
│   │   │   ├── OHSlotAllocationPage.tsx  # HPTR set-making + balancing (OH_OPERATOR)
│   │   │   └── MyProfile.tsx        #   User profile page
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── services/                # Axios API client + React Query
│   │   │   ├── oak1Camera.ts        #   OAK-1 camera companion client
│   │   │   └── workOrderService.ts  #   Work Order API client
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
│   ├── ocr_images_to_excel.py      # Batch OCR → Excel export utility
│   ├── register_bridge_tasks.ps1   # Register hardware bridges as Windows Scheduled Tasks
│   ├── reset_and_seed_full.py       # Full DB reset + re-seed
│   ├── run_native.sh               # Start full stack natively (no Docker)
│   ├── seed_data.py                 # Dev data seeder
│   ├── seed_demo_data.py            # Demo data for presentations
│   ├── stop_native.sh              # Stop the native stack
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
WorkOrder ──► Blade ◄── Measurement (weight, rocking, creep)  │
  (90 blades per WO)  │                                        │
                       ├──► SlotAllocation (slot, stage)      │
                       ├──► WorkflowLog (from→to, metadata)   │
                       ├──► Attachment (file_path, ocr_scan)  │
                       ├──► Notification (title, is_read)     │
                       └──► LptrBalancingCheck (stage 1/2)    │
                                                              │
Station ◄── Blade (current_station)                           │
Station ◄── User (home_station)                               │
                                                              │
Role ◄──► Permission (resource + action pairs)                │
User ◄──► Role (user_roles junction)                         ◄┘
```

### WorkOrder (replaces BatchGroup)

One Work Order is created per set of blades entered together. It carries the common identity fields shared by all 90 blades and drives the 90-row grid entry workflow.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `work_order_number` | VARCHAR(64) UNIQUE | MRO work order — primary routing key |
| `shop_order_number` | VARCHAR(64) | Internal shop order |
| `part_number` | VARCHAR(64) | Drawing/part number |
| `blade_type` | ENUM | `LPTR` or `HPTR` — fixed for all blades |
| `engine_number` | VARCHAR(64) | Parent engine |
| `engine_hours` | VARCHAR(64) | Engine total hours at removal |
| `component_hours` | VARCHAR(64) | Blade individual hours (defaults to engine_hours) |
| `is_entry_complete` | BOOLEAN | True once all 90 rows have melt + weight |
| `entry_completed_at` | TIMESTAMP | When entry was completed |
| `is_rocking_creep_complete` | BOOLEAN | True once rocking/creep values are locked |
| `created_at`, `updated_at` | TIMESTAMP | Audit timestamps |

### Blade (Central Entity)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `serial_number` | VARCHAR(64) | Positional S.No within the Work Order (01–90, zero-padded); unique per `work_order_id`, not globally |
| `work_order_id` | UUID FK → work_orders | RESTRICT on delete |
| `work_order_number` | VARCHAR(64) | Denormalised copy of `work_order.work_order_number` |
| `shop_order_number` | VARCHAR(64) | Copied from Work Order |
| `part_number` | VARCHAR(64) | Copied from Work Order |
| `melt_number` | VARCHAR(64) | Material traceability |
| `engine_number` | VARCHAR(64) | Parent engine |
| `engine_hours` | VARCHAR(64) | Engine total hours at removal |
| `component_hours` | VARCHAR(64) | Blade individual hours at removal |
| `blade_type` | ENUM | `LPTR` or `HPTR` |
| `status` | ENUM | 14 states (see state machine) |
| `current_station_id` | UUID FK → stations | |
| `created_by_id` | UUID FK → users | |
| `assigned_to_id` | UUID FK → users | |
| `ocr_melt_number` | VARCHAR(64) | OCR-extracted melt number |
| `ocr_mismatch_flag` | BOOLEAN | Set when OCR disagrees with manual entry |
| `ocr_mismatch_notes` | TEXT | Explanation of the mismatch |
| `deleted_at` | TIMESTAMP | Soft delete |

**Unique constraint:** `uq_blade_workorder_serial` on `(work_order_id, serial_number)`.

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

**Unique constraint:** `uq_measurement_blade_type` on `(blade_id, measurement_type)` — one row per type per blade.

**Note:** The `height_data` JSONB column (DTI height positions) was removed. DTI readings are captured live via the WebSocket bridge but are no longer persisted.

**Auto-transition:** Recording a measurement on a blade in `OH_INSPECTION` or `REOPENED` automatically transitions it to `MEASUREMENTS_RECORDED`.

### SlotAllocation (updated)

Added two fields for LPTR two-stage allocation:

| Field | Type | Notes |
|-------|------|-------|
| `stage` | INTEGER | LPTR allocation stage (1 or 2); `null` for HPTR / legacy rows |
| `group_id` | VARCHAR(64) | Optional group label for staged sets |

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

### LPTR Balancing Records (new)

Three new models support the LPTR two-stage balancing audit trail:

| Model | Table | Purpose |
|-------|-------|--------|
| `LptrEmptyRotorReading` | `lptr_empty_rotor_readings` | Empty-rotor unbalance measurement before blade load |
| `LptrBalancingCheck` | `lptr_balancing_checks` | Measured unbalance at each stage (stage 1 / stage 2) |
| `LptrManualCorrection` | `lptr_manual_corrections` | Rearrangement, adjustment, or replacement requests |

**`LptrCorrectionType` enum:** `REARRANGEMENT` / `BALANCING_ADJUSTMENT` / `MANUFACTURER_REPLACEMENT_REQUEST`

**`LPTR_UNBALANCE_LIMIT_G`** constant defines the pass/fail threshold for balancing checks.

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

### ~~BatchGroup~~ (removed)

`BatchGroup` has been replaced by `WorkOrder` (see above). The `batch_number` column on blades and the `batches` endpoint have both been removed. The Work Order concept provides richer lifecycle tracking (90-row grid, `is_entry_complete`, `is_rocking_creep_complete`) with a cleaner one-to-many relationship.

**Batch size:** `BLADES_PER_WORK_ORDER = 90` blades per Work Order. One Work Order covers one `blade_type` only (LPTR or HPTR, never mixed).

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

Any active state → REJECTED → (SUPER_ADMIN) → REOPENED → OH_INSPECTION
```

**14 total states** (`ON_HOLD` removed — it was unreachable from any UI path): CREATED, OH_INSPECTION, MEASUREMENTS_RECORDED, SENT_TO_ASSEMBLY, ASSEMBLY_RECEIVED, ASSEMBLY_VERIFIED, SLOT_ASSIGNED, BALANCING_IN_PROGRESS, BALANCING_COMPLETED, RETURNED_TO_OH, FINAL_VERIFICATION, COMPLETED, REJECTED, REOPENED.

**HPTR vs LPTR paths:** LPTR blades follow the full flow through assembly. HPTR blades stay at the OH station entirely — they skip SENT_TO_ASSEMBLY / ASSEMBLY_RECEIVED / ASSEMBLY_VERIFIED — and are assigned slots directly by OH_OPERATOR.

### Base Transitions (all blade types)

| From | To | Actor | Notes |
|------|----|-------|-------|
| CREATED | OH_INSPECTION | System | Auto on Work Order complete |
| OH_INSPECTION | MEASUREMENTS_RECORDED | OH_OPERATOR | Auto on first measurement save |
| OH_INSPECTION | REJECTED | Any operator | |
| MEASUREMENTS_RECORDED | SENT_TO_ASSEMBLY | OH_OPERATOR | LPTR only |
| MEASUREMENTS_RECORDED | REJECTED | Any operator | |
| SENT_TO_ASSEMBLY | ASSEMBLY_RECEIVED | ASSEMBLY_OPERATOR | Via receive endpoint |
| ASSEMBLY_RECEIVED | ASSEMBLY_VERIFIED | ASSEMBLY_OPERATOR | Via accept endpoint |
| ASSEMBLY_RECEIVED | REJECTED | ASSEMBLY_OPERATOR | Via reject endpoint |
| ASSEMBLY_VERIFIED | SLOT_ASSIGNED | ASSEMBLY_OPERATOR | After HAL slot assignment |
| SLOT_ASSIGNED | BALANCING_IN_PROGRESS | ASSEMBLY_OPERATOR | |
| BALANCING_IN_PROGRESS | BALANCING_COMPLETED | ASSEMBLY_OPERATOR | |
| BALANCING_COMPLETED | RETURNED_TO_OH | ASSEMBLY_OPERATOR | LPTR only |
| RETURNED_TO_OH | FINAL_VERIFICATION | OH_OPERATOR | |
| FINAL_VERIFICATION | COMPLETED | OH_OPERATOR | |
| REJECTED | REOPENED | SUPER_ADMIN | |
| REOPENED | OH_INSPECTION | System | |

### HPTR Extra Edges (`EXTRA_TRANSITIONS_BY_TYPE`)

When `blade.blade_type == HPTR`, additional transitions are unlocked:

| From | To | Notes |
|------|----|-------|
| MEASUREMENTS_RECORDED | SLOT_ASSIGNED | Skip assembly entirely |
| BALANCING_COMPLETED | FINAL_VERIFICATION | Direct to final QA (no RETURNED_TO_OH) |
| BALANCING_COMPLETED | MEASUREMENTS_RECORDED | Reset for rebalancing |
| SLOT_ASSIGNED | MEASUREMENTS_RECORDED | Redo slot allocation |
| BALANCING_IN_PROGRESS | MEASUREMENTS_RECORDED | Abort and redo |

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

### Step 1 — Receive Work Order

```
POST /assembly/work-orders/{work_order_number}/receive
→ All blades in WO: SENT_TO_ASSEMBLY → ASSEMBLY_RECEIVED
→ Creates AssemblyBladeRecord per blade (copies OH FINAL measurements)
→ Creates BatchEvent(event_type=RECEIVED_BY_ASSEMBLY)
→ Notifies OH_OPERATORs

GET /assembly/work-orders/{work_order_number}/progress
→ Returns { total_expected, assembly_received, assembly_verified, rejected }
```

### Step 2 — Verify Each Blade (assessment only — no status change)

The operator QR-scans each blade, enters Assembly-side measurements, and calls verify. **This step does NOT change `blade.status`** — it only updates the `AssemblyBladeRecord` and returns a suggested action.

```
POST /assembly/blades/{blade_id}/verify
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
| POST | `/assembly/work-orders/{work_order_number}/receive` | ASSEMBLY_OPERATOR | Receive work order; transitions all blades to ASSEMBLY_RECEIVED |
| GET | `/assembly/work-orders/{work_order_number}/receipt` | ASSEMBLY_OPERATOR / QA_VIEWER | Receipt details |
| GET | `/assembly/work-orders/{work_order_number}/progress` | ASSEMBLY_OPERATOR / QA_VIEWER | Verification progress (LPTR: ASSEMBLY_VERIFIED count; HPTR: MEASUREMENTS_RECORDED+ count) |
| GET | `/assembly/work-orders/{work_order_number}/blades` | ASSEMBLY_OPERATOR / QA_VIEWER | Blades with AssemblyVerificationStatus |
| POST | `/assembly/blades/{blade_id}/verify` | ASSEMBLY_OPERATOR | Assess vs OH records (no BladeStatus change) |
| POST | `/assembly/blades/{blade_id}/accept` | ASSEMBLY_OPERATOR | Accept → ASSEMBLY_VERIFIED |
| POST | `/assembly/blades/{blade_id}/reject` | ASSEMBLY_OPERATOR | Reject → REJECTED |
| POST | `/assembly/work-orders/{work_order_number}/start-setmaking` | ASSEMBLY_OPERATOR | Gate check; LPTR requires all ASSEMBLY_VERIFIED; HPTR requires all MEASUREMENTS_RECORDED+ |

---

## 7. API Reference

Base path: `/api/v1`  
**17 sub-routers** registered in `backend/app/api/v1/router.py`.

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
| GET | `/blades/{id}/qr` | Any | Generate QR code data for blade |
| POST | `/blades/{id}/send-to-assembly` | OH_OPERATOR | Transition to SENT_TO_ASSEMBLY |
| POST | `/blades/{id}/return-to-oh` | ASSEMBLY_OPERATOR | Transition to RETURNED_TO_OH |
| POST | `/blades/{id}/complete` | OH_OPERATOR / ASSEMBLY_OPERATOR | Transition to COMPLETED |
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
  &work_order_number=WO-2026-001
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
| POST | `/blades/{id}/measurements` | OH_OPERATOR | Record weight; auto-transitions to MEASUREMENTS_RECORDED |
| GET | `/blades/{id}/measurements` | Any | Measurement history |
| GET | `/measurements/{id}` | Any | Single measurement |
| PUT | `/measurements/{id}` | OH_OPERATOR | Update (pre-approval only) |
| PATCH | `/blades/{id}/rocking-creep` | OH_OPERATOR | Save rocking/creep independently; creates INITIAL if none exists |
| POST | `/measurements/{id}/approve` | OH_OPERATOR / SUPER_ADMIN | QA sign-off (was QA_VIEWER) |

### Slots

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/slots/assign` | ASSEMBLY_OPERATOR | Assign blade to a slot |
| POST | `/slots/reassign` | ASSEMBLY_OPERATOR | Reassign blade to a new slot (updates previous_slot_number) |
| PUT | `/slots/{slot_id}/balancing` | ASSEMBLY_OPERATOR | Record balancing result |
| GET | `/slots/` | Any | List active slot allocations (paginated, filterable) |
| GET | `/slots/blade/{blade_id}` | Any | Get current active slot for a blade |

### Work Orders (replaces Batches)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/work-orders/` | OH_OPERATOR | Create Work Order + 90 scaffold blade rows |
| GET | `/work-orders/` | Any | Paginated list |
| GET | `/work-orders/{wo_number}` | Any | Full detail including all 90 rows |
| PUT | `/work-orders/{wo_number}` | OH_OPERATOR | Update header fields |
| GET | `/work-orders/{wo_number}/rows` | Any | List all 90 blade rows |
| PUT | `/work-orders/{wo_number}/rows/{s_no}` | OH_OPERATOR | Autosave single row (melt, weight, OCR) |
| POST | `/work-orders/{wo_number}/rows/bulk-import` | OH_OPERATOR | Excel file import (partial success) |
| POST | `/work-orders/{wo_number}/complete` | OH_OPERATOR | Lock entry; transitions all blades CREATED→OH_INSPECTION→MEASUREMENTS_RECORDED |
| POST | `/work-orders/{wo_number}/send-to-assembly` | OH_OPERATOR | LPTR: bulk SENT_TO_ASSEMBLY |
| GET | `/work-orders/{wo_number}/rocking-creep` | Any | Rocking/creep for all blades |
| POST | `/work-orders/{wo_number}/rocking-creep/complete` | OH_OPERATOR | Lock rocking/creep |
| POST | `/work-orders/{wo_number}/assign-slot` | ASSEMBLY_OPERATOR / OH_OPERATOR | Run HAL + assign slots |
| GET | `/work-orders/{wo_number}/slot-summary` | Any | Slot occupancy by W1/W2 |
| POST | `/work-orders/{wo_number}/events` | ASSEMBLY_OPERATOR | Log batch event |
| GET | `/work-orders/{wo_number}/events` | Any | Batch event history |
| GET | `/work-orders/{wo_number}/progress` | Any | Verification progress counts |
| POST | `/work-orders/{wo_number}/accept` | OH_OPERATOR | Accept returned WO from Assembly |
| GET | `/work-orders/{wo_number}/blades` | Any | All blades in this WO |

### Assembly (Section 6 for detail)

See [Section 6](#6-assembly-verification--set-making) for the full assembly verification workflow.

> Note: the per-blade endpoints (`verify`, `accept`, `reject`) no longer require a `batch_number` query parameter — they now resolve the work order from the blade record directly.

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/assembly/work-orders/{work_order_number}/receive` | ASSEMBLY_OPERATOR | Receive; transitions all blades → ASSEMBLY_RECEIVED |
| GET | `/assembly/work-orders/{work_order_number}/receipt` | ASSEMBLY_OPERATOR / QA_VIEWER | Receipt details |
| GET | `/assembly/work-orders/{work_order_number}/progress` | ASSEMBLY_OPERATOR / QA_VIEWER | Verification progress counts |
| GET | `/assembly/work-orders/{work_order_number}/blades` | ASSEMBLY_OPERATOR / QA_VIEWER | Blades with AssemblyVerificationStatus |
| POST | `/assembly/blades/{blade_id}/verify` | ASSEMBLY_OPERATOR | Assess vs OH — no BladeStatus change |
| POST | `/assembly/blades/{blade_id}/accept` | ASSEMBLY_OPERATOR | Accept → ASSEMBLY_VERIFIED |
| POST | `/assembly/blades/{blade_id}/reject` | ASSEMBLY_OPERATOR | Reject → REJECTED |
| POST | `/assembly/work-orders/{work_order_number}/start-setmaking` | ASSEMBLY_OPERATOR | Gate check only |

### LPTR Balancing (new)

Prefix: `/lptr`. Requires ASSEMBLY_OPERATOR or SUPER_ADMIN.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lptr/{wo_number}/empty-rotor` | Get empty-rotor reading for this WO |
| POST | `/lptr/{wo_number}/empty-rotor` | Save empty-rotor unbalance measurement |
| GET | `/lptr/{wo_number}/balancing-check` | Get stage 1/2 balancing check records |
| POST | `/lptr/{wo_number}/balancing-check` | Save balancing check (pass/fail vs LPTR_UNBALANCE_LIMIT_G) |
| GET | `/lptr/{wo_number}/manual-correction` | Get manual correction records |
| POST | `/lptr/{wo_number}/manual-correction` | Log a correction (REARRANGEMENT / BALANCING_ADJUSTMENT / MANUFACTURER_REPLACEMENT_REQUEST) |

### Reports

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/reports/` | Any | Request async generation (202, returns Report ID) |
| GET | `/reports/` | Any | List reports |
| GET | `/reports/{id}` | Any | Status + metadata |
| DELETE | `/reports/{id}` | Any | Delete report record + file |
| GET | `/reports/{id}/download` | Any | StreamingResponse download |
| POST | `/reports/export/blades` | Any | Sync Excel export (≤5000 rows) |
| GET | `/reports/export/batch` | Any | Sync export for one WO (`?work_order_number=&format=excel\|pdf`) |
| POST | `/reports/export/hptr-slots` | OH_OPERATOR | HPTR slot allocation export (W1 slots 1-45 / W2 slots 46-90) |
| POST | `/reports/export/lptr-slots` | ASSEMBLY_OPERATOR | LPTR slot export + Balancing & Corrections audit sheet |

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
| GET | `/sync/blades` | Blade snapshot. Filters: `?work_order_number=`, `?status=`. Response: `OHSyncResponse` with flat field `weight` (not `weight_grams`) |
| GET | `/sync/work-orders/{wo_number}` | Single Work Order snapshot |

`station_role` and `station_name` in `/sync/status` are set via `STATION_ROLE` (not `STATION_TYPE`) and `STATION_NAME` env vars.

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
  "work_order_number": "WO-2026-001",
  "serial_number": "01"
}
```

### Report Structure (Async — POST /reports/)

The async generator (`backend/app/reports/generator.py`) produces **5 sheets**:

| Sheet | Contents |
|-------|----------|
| 1 — Summary | S.No, melt, WO number, status, station, created, updated |
| 2 — Measurements | Type, weight, static moment, rocking, creep, date, station |
| 3 — Slot Allocations | S.No, slot #, stage, group_id, balanced flag, imbalance value |
| 4 — Workflow History | From/to status, actor, timestamp |
| 5 — Work Order Traceability | WO number, S.No, melt, blade type, status, slot, rocking, creep |

A **Dashboard Summary** report (separate type) additionally includes: total blade count, blades by status, blades by station, rejection rate %, average processing hours.

### Sync Export Endpoints (POST /reports/export/...)

Four synchronous (inline) export endpoints return files directly without creating a Report record:

| Endpoint | Output | Contents |
|----------|--------|----------|
| `POST /export/blades` | Excel | Up to 5000 blade rows with all fields; accepts same filters as `GET /blades/` |
| `GET /export/batch?work_order_number=&format=excel\|pdf` | Excel or PDF | Full single-WO report (all 5 sheets in Excel; styled PDF) |
| `POST /export/hptr-slots` | Excel | HPTR slot allocation with **W1/W2 split** at slot 45 (slots 1-45 = W1, 46-90 = W2) |
| `POST /export/lptr-slots` | Excel | LPTR slot allocation + **Balancing & Corrections** audit sheet (empty-rotor readings, stage 1/2 checks, all manual corrections) |

The IRS logical sections (A–G, described in Section 13) map across the async report sheets.

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
| Inspection Station | `blade.current_station_id → station.name` |

#### Section B — OCR Verification

| Field | Source |
|-------|--------|
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
| `nginx` | nginx:1.27-alpine | Entry point; port 80 (HTTP-only — private LAN deployment) |

All services share Docker network `blade_rocking_net`.

### Volumes

```
postgres_data   — persistent PostgreSQL data
redis_data      — persistent Redis AOF/RDB
./uploads       — file attachments + OCR scans (bind mount)
./reports       — generated reports (bind mount)
./logs          — structured logs (bind mount)
```

### Native Stack (no Docker)

For workstations without Docker, two scripts manage the full stack natively:

| Script | Purpose |
|--------|--------|
| `scripts/run_native.sh` | Installs PostgreSQL + Redis via apt (if absent), creates `blade_rocking` DB and `blade_user` role, writes `backend/.env`, starts uvicorn + celery + vite in background |
| `scripts/stop_native.sh` | Stops uvicorn, celery, and vite processes started by `run_native.sh` |

### Windows Scheduled Tasks (Hardware Bridges)

`scripts/register_bridge_tasks.ps1` registers the three hardware bridge scripts as Windows Scheduled Tasks:

- **Trigger:** At user logon (20 second delay to allow the OS to settle)
- **Restart:** Up to 999 times at 1-minute intervals if the process exits
- **Tasks registered:** `BladeRocking_WeighingBridge`, `BladeRocking_DTIBridge`, `BladeRocking_OAK1Camera`
- **Python path:** `C:\Users\ADMIN\AppData\Local\Python\bin\python.exe`
- **Scripts dir:** `C:\blade-rocking\scripts`

Run once as Administrator: `powershell -ExecutionPolicy Bypass -File scripts/register_bridge_tasks.ps1`

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

Key migrations applied:
- `20260529_initial_schema` — bootstrap
- `20260601_add_blade_type` — `blade_type` ENUM (LPTR/HPTR)
- `20260616_add_sent_to_assembly_batch_event` — batch event type additions
- `20260630_assembly_workflow` — ASSEMBLY_RECEIVED + ASSEMBLY_VERIFIED states
- `20260714_remove_height_dti_positions` — drop `height_data` JSONB from measurements
- `20260715_drop_nomenclature_ocr_serial` — drop `nomenclature`, `ocr_serial_number`, `batch_number`, `rejection_reason_id` from blades
- `20260716_add_work_order` — `work_orders` table + `work_order_id` FK on blades
- `20260720_slot_stage_group` — `stage` + `group_id` on slot_allocations
- `20260721_lptr_balancing_tables` — `lptr_empty_rotor_readings`, `lptr_balancing_checks`, `lptr_manual_corrections`

---

## 15. Security

| Control | Implementation |
|---------|----------------|
| Password hashing | bcrypt, cost factor 12 |
| JWT signing | PyJWT 2.x, HS256, 64-char random `SECRET_KEY` |
| Token revocation | Redis blacklist keyed on JWT `jti` |
| Transport security | HTTP-only on private LAN (no TLS — internal network deployment) |
| CORS | Origin whitelist via `CORS_ORIGINS` env var |
| Rate limiting | NGINX `limit_req` — API: 30r/s burst=60; auth: 20r/min burst=10; static: 30r/s burst=50 |
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

22 application routes + 5 redirect aliases. Role-based routing enforced client-side.

| Route | Page | Minimum Role | Notes |
|-------|------|-------------|-------|
| `/login` | LoginPage | Public | |
| `/` | RoleHome (redirect) | Authenticated | |
| `/dashboard` | DashboardPage | SUPER_ADMIN | |
| `/qa-dashboard` | QaDashboardPage | QA_VIEWER | Camera source toggle for OAK-1 |
| `/blades/new` | BladeEntryPage | OH_OPERATOR | Redirected from `/work-orders/new` |
| `/blades/:workOrderNumber/entry` | BladeEntryPage | OH_OPERATOR | 90-row grid entry |
| `/blades/:id` | BladeDetailPage | Any | |
| `/blades/:id/timeline` | WorkflowTimelinePage | Any | |
| `/oh-queue` | OHQueuePage | OH_OPERATOR | |
| `/oh/slot-allocation` | OHSlotAllocationPage | OH_OPERATOR | HPTR set-making + balancing at OH |
| `/assembly-queue` | AssemblyQueuePage | ASSEMBLY_OPERATOR | |
| `/slots` | SlotAllocationPage | ASSEMBLY_OPERATOR | LPTR slot assignment |
| `/rocking-creep` | RockingCreepPage | OH_OPERATOR | |
| `/assembly/verify/:workOrderNumber` | AssemblyVerificationPage | ASSEMBLY_OPERATOR | |
| `/batch-tracking` | BatchTrackingPage | Any | Lists Work Orders (not batches) |
| `/work-orders/:woNumber/modify` | ModifyBatchPage | ASSEMBLY_OPERATOR | |
| `/work-orders/:woNumber/accept` | AcceptBatchPage | OH_OPERATOR | Accept returned WO |
| `/reports` | ReportsPage | Any | Async + sync export triggers |
| `/users` | UserManagementPage | SUPER_ADMIN | |
| `/notifications` | NotificationsPage | Authenticated | |
| `/settings` | SettingsPage | Authenticated | |
| `/profile` | MyProfile | Authenticated | User profile + password change |

**Redirect aliases:** `/work-orders` → `/batch-tracking`; `/batches/:n/modify` → `/work-orders/:n/modify`; `/batches/:n/accept` → `/work-orders/:n/accept`; `/blades/new` → `/blades/:wn/entry`; `/assembly/verify/:n` kept for legacy links.

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
STATION_ROLE=ASSEMBLY          # "OH" or "ASSEMBLY" — controls sync/status response
STATION_NAME="Assembly Station — 720 Hanger"   # Used in /sync/status response
OH_SYNC_URL=http://192.168.1.50

# OCR backend (default: paddleocr — set mock for dev without PaddleOCR installed)
OCR_PROVIDER=paddleocr         # mock | tesseract | paddleocr — default is paddleocr

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
