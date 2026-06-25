# Blade Rocking & Creep Test Management System

A full-stack web application that manages the complete lifecycle of turbine blades through overhaul (OH) inspection, assembly slot allocation, balancing, and final quality verification.

---

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │                   NGINX :80/443               │
                        │  rate-limit · gzip · security headers · TLS   │
                        └─────────────┬──────────────────┬─────────────┘
                                      │                  │
                         /api/v1/*    │                  │  /*
                                      ▼                  ▼
                        ┌─────────────────┐   ┌──────────────────────┐
                        │  FastAPI :8000  │   │  React/Vite (NGINX)  │
                        │  (4 workers)    │   │  :80 (static files)  │
                        └────────┬────────┘   └──────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
                    ▼            ▼            ▼
            ┌──────────┐  ┌──────────┐  ┌──────────────┐
            │ Postgres │  │  Redis   │  │ Celery Worker│
            │   :5432  │  │  :6379   │  │ (reports Q)  │
            └──────────┘  └──────────┘  └──────────────┘
```

### Role-Based Access

| Role               | Capabilities |
|--------------------|--------------|
| `SUPER_ADMIN`      | Full access including user management |
| `OH_OPERATOR`      | Create blades, record measurements, send to assembly, reject, reopen |
| `ASSEMBLY_OPERATOR`| Assign slots, update balancing, return to OH |
| `QA_VIEWER`        | Read-only access to all blade data and reports |

---

## Quick Start (Docker)

### Prerequisites

- Docker >= 24
- Docker Compose >= 2.20
- (Optional) Make

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/your-org/blade-rocking.git
cd blade-rocking

# 2. Create environment file
cp .env.example .env
# Edit .env and set POSTGRES_PASSWORD and SECRET_KEY at minimum

# 3. Start all services
docker-compose up -d

# 4. Run database migrations
docker-compose exec backend alembic upgrade head

# 5. Seed development data
docker-compose exec backend python ../scripts/seed_data.py
```

### Service URLs

| Service            | URL |
|--------------------|-----|
| Web Application    | http://localhost |
| API (Swagger UI)   | http://localhost/docs |
| API (ReDoc)        | http://localhost/redoc |
| Backend (direct)   | http://localhost:8000 |

---

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start a local Postgres and Redis (e.g. via Docker):
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:15-alpine
docker run -d -p 6379:6379 redis:7-alpine

# Apply migrations
alembic upgrade head

# Seed data
python ../scripts/seed_data.py

# Start the development server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm ci
npm run dev    # Vite dev server on http://localhost:5173
```

### Using Make

```bash
make install        # Install all dependencies
make dev-backend    # FastAPI with hot-reload
make dev-frontend   # Vite dev server
make migrate        # Apply DB migrations
make seed           # Seed development data
make test           # Run full test suite
make test-coverage  # Tests + HTML coverage report
make lint           # ruff + mypy
make up             # docker-compose up -d
make down           # docker-compose down
make logs           # Tail all container logs
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/blade_rocking` | Async PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis DSN |
| `SECRET_KEY` | *(random on start)* | JWT signing secret — **set explicitly in production** |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token TTL in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL in days |
| `ENVIRONMENT` | `dev` | `dev` / `staging` / `prod` |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |
| `POSTGRES_DB` | `blade_rocking` | Postgres database name |
| `POSTGRES_USER` | `blade_user` | Postgres username |
| `POSTGRES_PASSWORD` | *(required)* | Postgres password |
| `CORS_ORIGINS` | *(empty — all in dev)* | Comma-separated list of allowed origins |
| `MAX_FILE_SIZE_MB` | `10` | Maximum file upload size |
| `SMTP_HOST` | *(optional)* | SMTP server for email notifications |
| `SMTP_USER` | *(optional)* | SMTP username |
| `SMTP_PASSWORD` | *(optional)* | SMTP password |
| `EMAILS_FROM_ADDRESS` | *(optional)* | From address for outbound emails |

---

## API Documentation

Interactive Swagger UI is available at `/docs` (non-production environments only).

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Authenticate and obtain JWT tokens |
| `POST` | `/api/v1/auth/refresh` | Refresh an access token |
| `GET`  | `/api/v1/auth/me` | Current user profile |
| `POST` | `/api/v1/blades/` | Register a new blade |
| `GET`  | `/api/v1/blades/` | List / search blades (paginated) |
| `GET`  | `/api/v1/blades/{id}` | Blade detail |
| `POST` | `/api/v1/blades/{id}/send-to-assembly` | OH → Assembly transition |
| `POST` | `/api/v1/blades/{id}/reject` | Reject a blade |
| `POST` | `/api/v1/blades/{id}/reopen` | Reopen a rejected blade |
| `GET`  | `/api/v1/blades/{id}/history` | Workflow audit trail |
| `POST` | `/api/v1/blades/{id}/attachments` | Upload file attachment |
| `GET`  | `/api/v1/reports/` | List generated reports |
| `POST` | `/api/v1/reports/` | Request a new report (async) |
| `GET`  | `/api/v1/users/` | List users (SUPER_ADMIN only) |
| `GET`  | `/health` | Application health check |

---

## Default Development Users

Seeded by `scripts/seed_data.py`:

| Role | Email | Password |
|------|-------|----------|
| Super Admin | `admin@bladerocking.com` | `Admin@123` |
| OH Operator | `oh.operator@bladerocking.com` | `Test@123` |
| Assembly Operator | `assembly@bladerocking.com` | `Test@123` |
| QA Viewer | `qa.viewer@bladerocking.com` | `Test@123` |

> **Warning:** Change all passwords before deploying to any non-development environment.

---

## Blade Workflow

```
CREATED ──► OH_INSPECTION ──► MEASUREMENTS_RECORDED ──► SENT_TO_ASSEMBLY
                │                      │                        │
                └──► REJECTED ◄────────┘◄───────────────────────┘
                         │
                      REOPENED ──► OH_INSPECTION
                                                   SENT_TO_ASSEMBLY
                                                          │
                                                   SLOT_ASSIGNED
                                                          │
                                                BALANCING_IN_PROGRESS
                                                          │
                                                 BALANCING_COMPLETED
                                                          │
                                                   RETURNED_TO_OH
                                                          │
                                                  FINAL_VERIFICATION
                                                          │
                                                       COMPLETED
```

Any state except `COMPLETED` can be placed on hold (`ON_HOLD`) and resumed.

---

## Project Structure

```
blade-rocking/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # FastAPI route handlers
│   │   ├── core/               # Config, security, dependencies
│   │   ├── db/                 # Engine, session, base model
│   │   ├── middleware/         # Audit logging, rate limiting
│   │   ├── models/             # SQLAlchemy ORM models + enums
│   │   ├── notifications/      # WebSocket push
│   │   ├── ocr/                # Tesseract OCR integration
│   │   ├── repositories/       # Data access layer
│   │   ├── reports/            # Celery tasks, PDF/Excel generation
│   │   ├── schemas/            # Pydantic I/O schemas
│   │   ├── services/           # Business logic
│   │   ├── tests/              # pytest suite (unit + API)
│   │   ├── utils/              # Helpers
│   │   ├── workflows/          # State machine
│   │   └── main.py             # Application factory
│   ├── alembic/                # Database migrations
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/                    # React + TypeScript source
│   ├── Dockerfile
│   └── package.json
├── nginx/
│   └── nginx.conf              # Reverse-proxy configuration
├── scripts/
│   └── seed_data.py            # Development data seeder
├── .github/workflows/
│   └── ci.yml                  # GitHub Actions CI/CD pipeline
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## Running Tests

```bash
# Full suite
make test

# Unit tests only (no DB required)
make test-unit

# API integration tests
make test-api

# With coverage report (fails below 70%)
make test-coverage
```

CI runs on every push and pull request via GitHub Actions.  Coverage is
uploaded to Codecov automatically.

---

## Contributing

1. Fork the repository and create a feature branch from `develop`.
2. Follow the existing code style — run `make lint` and `make format` before committing.
3. Add or update tests for any changed behaviour.
4. Submit a pull request against `develop` with a clear description of the change.

All PRs must pass the CI pipeline (tests + lint + type-check) before merging.

---

## License

Proprietary — all rights reserved.  
Contact: Meridian Data Labs · amit@meridiandatalabs.com
