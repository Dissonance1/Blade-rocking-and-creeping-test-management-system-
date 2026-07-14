# =============================================================================
# Blade Rocking & Creep Test Management System — Developer Makefile
#
# Usage:  make <target>
# =============================================================================

.PHONY: help install install-backend install-frontend \
        dev-backend dev-frontend \
        migrate migration seed \
        test test-coverage test-backend test-unit test-api \
        lint lint-backend format \
        up down logs build \
        oh-build oh-up oh-down oh-logs oh-migrate oh-shell oh-db \
        assembly-build assembly-up assembly-down assembly-logs assembly-migrate assembly-shell \
        clean

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR  := backend
FRONTEND_DIR := frontend
SCRIPTS_DIR  := scripts
ALEMBIC_DIR  := $(BACKEND_DIR)

# ---------------------------------------------------------------------------
# Default target
# ---------------------------------------------------------------------------
help:          ## Show this help message
	@echo ""
	@echo "  Blade Rocking & Creep Test Management System"
	@echo "  ─────────────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | sort \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# Installation
# =============================================================================

install: install-backend install-frontend  ## Install all dependencies (backend + frontend)

install-backend:  ## Install Python backend dependencies
	@echo ">>> Installing backend Python packages …"
	cd $(BACKEND_DIR) && pip install -r requirements.txt

install-frontend:  ## Install Node.js frontend dependencies
	@echo ">>> Installing frontend Node packages …"
	cd $(FRONTEND_DIR) && npm ci

# =============================================================================
# Development servers
# =============================================================================

dev-backend:  ## Start FastAPI development server with auto-reload
	@echo ">>> Starting FastAPI (http://localhost:8000) …"
	cd $(BACKEND_DIR) && uvicorn app.main:app \
		--host 0.0.0.0 \
		--port 8000 \
		--reload \
		--log-level debug

dev-frontend:  ## Start React/Vite development server
	@echo ">>> Starting Vite dev server (http://localhost:5173) …"
	cd $(FRONTEND_DIR) && npm run dev

# =============================================================================
# Database
# =============================================================================

migrate:  ## Apply all pending Alembic migrations (alembic upgrade head)
	@echo ">>> Running Alembic migrations …"
	cd $(ALEMBIC_DIR) && alembic upgrade head

migration:  ## Generate a new Alembic migration  (usage: make migration MSG="add index")
	@[ -n "$(MSG)" ] || (echo "ERROR: MSG is required, e.g.  make migration MSG=\"add index\"" && exit 1)
	@echo ">>> Generating migration: $(MSG)"
	cd $(ALEMBIC_DIR) && alembic revision --autogenerate -m "$(MSG)"

seed:  ## Seed the database with development fixtures
	@echo ">>> Seeding database …"
	cd $(BACKEND_DIR) && python ../$(SCRIPTS_DIR)/seed_data.py

# =============================================================================
# Testing
# =============================================================================

test:  ## Run the full test suite with verbose output
	@echo ">>> Running full test suite …"
	cd $(BACKEND_DIR) && pytest app/tests/ -v --tb=short --strict-markers

test-unit:  ## Run only unit tests
	@echo ">>> Running unit tests …"
	cd $(BACKEND_DIR) && pytest app/tests/unit/ -v --tb=short

test-api:  ## Run only API (integration) tests
	@echo ">>> Running API tests …"
	cd $(BACKEND_DIR) && pytest app/tests/api/ -v --tb=short

test-coverage:  ## Run tests with coverage report (fails under 70%)
	@echo ">>> Running tests with coverage …"
	cd $(BACKEND_DIR) && pytest \
		app/tests/ \
		--cov=app \
		--cov-report=html:htmlcov \
		--cov-report=term-missing \
		--cov-fail-under=70 \
		-v
	@echo ">>> HTML coverage report: $(BACKEND_DIR)/htmlcov/index.html"

# =============================================================================
# Code quality
# =============================================================================

lint: lint-backend  ## Run all linters

lint-backend:  ## Run ruff + mypy on the backend
	@echo ">>> ruff check …"
	cd $(BACKEND_DIR) && ruff check app/
	@echo ">>> mypy …"
	cd $(BACKEND_DIR) && mypy app/ --ignore-missing-imports

format:  ## Auto-format backend Python code with ruff
	@echo ">>> ruff format …"
	cd $(BACKEND_DIR) && ruff format app/

# =============================================================================
# Docker Compose
# =============================================================================

up:  ## Start all services in detached mode
	@echo ">>> docker compose up …"
	docker-compose up -d

down:  ## Stop and remove containers
	@echo ">>> docker compose down …"
	docker-compose down

logs:  ## Tail logs from all services (Ctrl+C to stop)
	docker-compose logs -f

build:  ## Build (or rebuild) all Docker images
	@echo ">>> Building Docker images …"
	docker-compose build

# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

ps:  ## Show status of all running containers
	docker-compose ps

restart:  ## Restart all services
	docker-compose restart

shell-backend:  ## Open a shell in the running backend container
	docker-compose exec backend /bin/bash

shell-db:  ## Open psql in the running postgres container
	docker-compose exec postgres psql -U $${POSTGRES_USER:-blade_user} -d $${POSTGRES_DB:-blade_rocking}

# =============================================================================
# OH Station (701 Hanger) — docker-compose.oh.yml
# =============================================================================

oh-build:  ## Build Docker images for OH station
	@echo ">>> Building OH station images …"
	docker-compose -f docker-compose.oh.yml --env-file .env.oh build

oh-up:  ## Start OH station services (requires .env.oh)
	@echo ">>> Starting OH station …"
	docker-compose -f docker-compose.oh.yml --env-file .env.oh up -d

oh-down:  ## Stop OH station services
	docker-compose -f docker-compose.oh.yml --env-file .env.oh down

oh-logs:  ## Tail OH station logs
	docker-compose -f docker-compose.oh.yml --env-file .env.oh logs -f

oh-migrate:  ## Run Alembic migrations on OH station
	docker-compose -f docker-compose.oh.yml --env-file .env.oh exec oh_backend alembic upgrade head

oh-shell:  ## Open shell in OH backend container
	docker-compose -f docker-compose.oh.yml --env-file .env.oh exec oh_backend /bin/bash

oh-db:  ## Open psql on OH station
	docker-compose -f docker-compose.oh.yml --env-file .env.oh exec oh_postgres \
	  psql -U $${POSTGRES_USER:-blade_user} -d $${POSTGRES_DB:-blade_rocking_oh}

# =============================================================================
# Assembly Station (720 Hanger) — docker-compose.assembly.yml
# =============================================================================

assembly-build:  ## Build Docker images for Assembly station
	@echo ">>> Building Assembly station images …"
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly build

assembly-up:  ## Start Assembly station services (requires .env.assembly)
	@echo ">>> Starting Assembly station …"
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly up -d

assembly-down:  ## Stop Assembly station services
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly down

assembly-logs:  ## Tail Assembly station logs
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly logs -f

assembly-migrate:  ## Run Alembic migrations on Assembly station
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly exec assembly_backend alembic upgrade head

assembly-shell:  ## Open shell in Assembly backend container
	docker-compose -f docker-compose.assembly.yml --env-file .env.assembly exec assembly_backend /bin/bash

# =============================================================================
# Housekeeping
# =============================================================================

clean:  ## Remove Python cache files and coverage artefacts
	@echo ">>> Cleaning caches …"
	find $(BACKEND_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND_DIR) -name "*.pyc" -delete 2>/dev/null || true
	rm -rf $(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/.coverage $(BACKEND_DIR)/coverage.xml
	@echo ">>> Done."
