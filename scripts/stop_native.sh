#!/usr/bin/env bash
# =============================================================================
# Stops the backend / celery / frontend processes started by run_native.sh.
#
# Postgres and Redis are left running as system services (they're shared,
# managed by systemd) — stop them yourself if needed:
#   sudo systemctl stop postgresql redis-server
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$ROOT_DIR/.native-run"

stop_one() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if [ ! -f "$pid_file" ]; then
    return
  fi
  local pid
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    echo ">>> Stopping $name (pid $pid)..."
    # Negative PID targets the whole process group (started with setsid),
    # so npm's forked vite child gets killed too, not just the npm wrapper.
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  else
    echo ">>> $name not running (stale pid file)"
  fi
  rm -f "$pid_file"
}

stop_one frontend
stop_one celery
stop_one backend

echo ">>> Done. Postgres/Redis system services left running."
