#!/usr/bin/env bash
# =============================================================================
# Blade Rocking & Creep Test Management System — Native (no Docker) run
#
# Starts Postgres, Redis, the FastAPI backend, the Celery worker, and the
# Vite frontend dev server directly on this machine — no containers.
#
# First run: installs postgresql/redis-server via apt if missing (needs sudo,
# will prompt for your password), creates the blade_rocking DB/role, and
# writes backend/.env pointed at localhost instead of docker service names.
# Safe to re-run — every step is idempotent.
#
# Usage:
#   ./scripts/run_native.sh          # start everything (backgrounded)
#   ./scripts/stop_native.sh         # stop everything this script started
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.native-run"
LOG_DIR="$ROOT_DIR/logs/native"
SECRETS_DIR="$RUN_DIR/secrets"

mkdir -p "$RUN_DIR" "$SECRETS_DIR" "$LOG_DIR" "$ROOT_DIR/uploads" "$ROOT_DIR/reports" "$ROOT_DIR/logs/backend" "$ROOT_DIR/logs/celery"

# Local-only credentials, generated once and persisted under .native-run/secrets
# (gitignored) instead of hardcoded in source — reused on every re-run so the
# Postgres role/DB and Redis requirepass stay consistent across restarts.
_get_or_create_secret() {
  local file="$SECRETS_DIR/$1"
  if [ ! -f "$file" ]; then
    (umask 177 && openssl rand -base64 24 | tr -d '\n=/+' > "$file")
  fi
  cat "$file"
}

PG_DB="blade_rocking"
PG_USER="blade_user"
PG_PASSWORD="$(_get_or_create_secret pg_password)"
REDIS_PASSWORD="$(_get_or_create_secret redis_password)"
BACKEND_PORT=8000
FRONTEND_PORT=3000

echo "=============================================="
echo " Blade Rocking & Creep — Native Run (no Docker)"
echo "=============================================="

# ---------------------------------------------------------------------------
# 1. PostgreSQL — install if missing, ensure running, create DB/role
# ---------------------------------------------------------------------------
if ! dpkg -s postgresql &>/dev/null; then
  echo ">>> Installing PostgreSQL (sudo required)..."
  sudo apt-get update -y
  sudo apt-get install -y postgresql
fi
sudo systemctl enable --now postgresql >/dev/null

echo ">>> Ensuring database role/DB exist..."
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$PG_USER') THEN
    CREATE ROLE $PG_USER LOGIN PASSWORD '$PG_PASSWORD';
  END IF;
END
\$\$;
SQL
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1; then
  sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" >/dev/null
fi

# ---------------------------------------------------------------------------
# 2. Redis — install if missing, ensure running, set password
# ---------------------------------------------------------------------------
if ! dpkg -s redis-server &>/dev/null; then
  echo ">>> Installing Redis (sudo required)..."
  sudo apt-get update -y
  sudo apt-get install -y redis-server
fi
sudo systemctl enable --now redis-server >/dev/null
redis-cli CONFIG SET requirepass "$REDIS_PASSWORD" >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 3. backend/.env — same credentials as the Docker .env, but "localhost"
#    instead of docker service names, and host paths instead of /app/*.
# ---------------------------------------------------------------------------
cat > "$BACKEND_DIR/.env" <<ENV
ENVIRONMENT=dev
DEBUG=true
SECRET_KEY=2eca5ad04c0759eb5b74cc6eb750ce092ea04ed78b0f00299107c9f70820e78f
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

POSTGRES_DB=$PG_DB
POSTGRES_USER=$PG_USER
POSTGRES_PASSWORD=$PG_PASSWORD
DATABASE_URL=postgresql+asyncpg://$PG_USER:$PG_PASSWORD@localhost:5432/$PG_DB

REDIS_PASSWORD=$REDIS_PASSWORD
REDIS_URL=redis://:$REDIS_PASSWORD@localhost:6379/0
CELERY_BROKER_URL=redis://:$REDIS_PASSWORD@localhost:6379/1
CELERY_RESULT_BACKEND=redis://:$REDIS_PASSWORD@localhost:6379/2

CORS_ORIGINS=["http://localhost:$FRONTEND_PORT","http://127.0.0.1:$FRONTEND_PORT"]

UPLOAD_DIR=$ROOT_DIR/uploads
REPORTS_DIR=$ROOT_DIR/reports
MAX_FILE_SIZE_MB=10

OCR_PROVIDER=mock

LOG_LEVEL=INFO
LOG_FORMAT=json
ENV

# ---------------------------------------------------------------------------
# 4. Backend virtualenv + migrations
# ---------------------------------------------------------------------------
VENV_DIR="$BACKEND_DIR/.venv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo ">>> Creating backend virtualenv..."
  python3.11 -m venv "$VENV_DIR" 2>/dev/null || python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

echo ">>> Setting up database schema..."
# This project's baseline Alembic migration is an intentional no-op — the
# schema is actually created via SQLAlchemy's create_all() at app startup
# (app/db/session.py:init_db, dev-only), and every migration after that
# baseline only carries INCREMENTAL diffs assuming that schema already
# exists. So on a genuinely fresh DB, "alembic upgrade head" alone fails
# (it tries to ALTER a table create_all() would have made, but never ran).
# Bootstrap accordingly: create_all() + stamp head on a fresh DB, or a
# normal "upgrade head" if the schema already exists (idempotent re-runs).
BLADES_EXISTS=$(cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -c "
import asyncio
from sqlalchemy import inspect
from app.db.session import engine

async def check():
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: inspect(c).has_table('blades'))

print(asyncio.run(check()))
")

if [ "$BLADES_EXISTS" != "True" ]; then
  echo ">>> Fresh database — creating schema (create_all) and stamping Alembic head..."
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/python" -c "
import asyncio
from app.db.session import init_db
asyncio.run(init_db())
")
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" stamp head)
else
  echo ">>> Applying any pending migrations..."
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head)
fi

# ---------------------------------------------------------------------------
# 5. Start backend (uvicorn, hot reload)
# ---------------------------------------------------------------------------
echo ">>> Starting backend on :$BACKEND_PORT..."
cd "$BACKEND_DIR"
setsid nohup "$VENV_DIR/bin/uvicorn" app.main:app --reload --port "$BACKEND_PORT" \
  > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
echo $! > "$RUN_DIR/backend.pid"
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# 6. Start Celery worker
# ---------------------------------------------------------------------------
echo ">>> Starting Celery worker..."
cd "$BACKEND_DIR"
setsid nohup "$VENV_DIR/bin/celery" -A app.worker worker \
  --loglevel=info -Q reports,celery --concurrency=2 --max-tasks-per-child=50 \
  > "$LOG_DIR/celery.log" 2>&1 < /dev/null &
echo $! > "$RUN_DIR/celery.pid"
cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# 7. Start frontend (Vite dev server — proxies /api and /ws to :8000 already,
#    see frontend/vite.config.ts, no extra env needed)
# ---------------------------------------------------------------------------
cd "$FRONTEND_DIR"
if [ ! -d node_modules ]; then
  echo ">>> Installing frontend dependencies..."
  npm install
fi
echo ">>> Starting frontend on :$FRONTEND_PORT..."
setsid nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 < /dev/null &
echo $! > "$RUN_DIR/frontend.pid"
cd "$ROOT_DIR"

sleep 3

echo
echo "=============================================="
echo " Running!"
echo "   Frontend:   http://localhost:$FRONTEND_PORT"
echo "   Backend:    http://localhost:$BACKEND_PORT/docs"
echo "   Logs:       $LOG_DIR/{backend,celery,frontend}.log"
echo "   Stop with:  ./scripts/stop_native.sh"
echo
echo " First time on an empty DB? Seed dev data with:"
echo "   $VENV_DIR/bin/python scripts/seed_data.py"
echo "=============================================="
