#!/bin/bash
# Ensure bind-mounted directories are writable by the appuser (uid 1001).
# The host creates these directories as uid 1000, so we chmod on startup.
set -e

for dir in /app/uploads /app/reports /app/logs; do
    if [ -d "$dir" ]; then
        chmod -R 777 "$dir" 2>/dev/null || true
    fi
done

exec "$@"
