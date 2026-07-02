#!/usr/bin/env bash
# =============================================================================
# Blade Rocking & Creep Test Management System — Local Deployment Script
#
# PRIVATE NETWORK — runs entirely on the local server, no internet needed.
# Run this script on the Linux server inside the plant/factory network.
#
# Usage:
#   First time:  ./scripts/deploy.sh --fresh
#   Update:      ./scripts/deploy.sh
#   With HTTPS:  ./scripts/deploy.sh --https
# =============================================================================
set -euo pipefail

COMPOSE="docker-compose"
FRESH=false
HTTPS=false

for arg in "$@"; do
  case $arg in
    --fresh)  FRESH=true ;;
    --https)  HTTPS=true ;;
  esac
done

echo "=============================================="
echo " Blade Rocking & Creep Test — Deploy"
echo "=============================================="

# 1. Verify .env exists
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in values."
  exit 1
fi

# 2. Create required host directories
mkdir -p uploads reports logs/backend logs/celery logs/nginx ssl
# Ensure all runtime directories are writable by Docker containers
chmod -R 777 uploads reports logs 2>/dev/null || true

# 3. Generate self-signed TLS cert if --https and no cert present
if [ "$HTTPS" = true ] && [ ! -f ssl/fullchain.pem ]; then
  echo ">>> Generating self-signed TLS certificate (valid 10 years)..."
  SERVER_IP=$(hostname -I | awk '{print $1}')
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout ssl/privkey.pem \
    -out ssl/fullchain.pem \
    -subj "/C=IN/O=ManufacturingPlant/CN=blade-rocking.local" \
    -addext "subjectAltName=IP:${SERVER_IP},DNS:blade-rocking.local"
  echo "    Certificate: ssl/fullchain.pem"
  echo "    Key:         ssl/privkey.pem"
  echo "    Server IP:   ${SERVER_IP}"
fi

# 4. Build Docker images (from local source — no internet pull needed after first build)
echo ">>> Building Docker images..."
$COMPOSE build --parallel

# 5. Stop old containers gracefully (if running)
echo ">>> Stopping existing containers..."
$COMPOSE down --remove-orphans || true

# 6. Start services
echo ">>> Starting services..."
$COMPOSE up -d

# 7. Wait for backend to be healthy
echo ">>> Waiting for backend to become healthy..."
for i in $(seq 1 30); do
  if $COMPOSE exec -T backend curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "    Backend is healthy."
    break
  fi
  if [ $i -eq 30 ]; then
    echo "ERROR: Backend did not start within 60 seconds."
    $COMPOSE logs backend | tail -30
    exit 1
  fi
  sleep 2
done

# 8. Run database migrations
echo ">>> Running database migrations..."
$COMPOSE exec -T backend alembic upgrade head

# 9. Seed database (first-time only)
if [ "$FRESH" = true ]; then
  echo ">>> Seeding database with initial data..."
  $COMPOSE exec -T backend python scripts/seed_data.py
fi

# 10. Final status
echo ""
echo "=============================================="
SERVER_IP=$(hostname -I | awk '{print $1}')
echo " Deployment complete!"
echo ""
echo " Access from any LAN machine:"
echo "   http://${SERVER_IP}/"
if [ "$HTTPS" = true ]; then
echo "   https://${SERVER_IP}/  (accept self-signed cert warning)"
fi
echo ""
echo " Default login credentials (change after first login):"
echo "   Admin:    admin@bladerocking.com / Admin@123"
echo "   OH Op:    oh.operator@bladerocking.com / Test@123"
echo "   Assembly: assembly@bladerocking.com / Test@123"
echo ""
echo " API docs:  http://${SERVER_IP}/docs"
echo " Logs:      docker-compose logs -f"
echo "=============================================="
