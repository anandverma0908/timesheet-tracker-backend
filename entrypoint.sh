#!/bin/bash
set -e

# Neon is always ready — skip pg_isready loop (pooler host doesn't support it)
# For self-hosted postgres, set PGHOST to re-enable the wait loop
if [ -n "${PGHOST}" ]; then
  echo "⏳ Waiting for postgres at ${PGHOST}..."
  until pg_isready -h "${PGHOST}" -U "${PGUSER:-trackly}" > /dev/null 2>&1; do
    sleep 1
  done
  echo "✅ Postgres ready"
fi

echo "🏗️  Creating base tables (idempotent)..."
PYTHONPATH=/app python scripts/init_db.py

echo "🔄 Running migrations..."
MIGRATE_URL="${DATABASE_URL_DIRECT:-$DATABASE_URL}"
DATABASE_URL="$MIGRATE_URL" alembic upgrade head
echo "✅ Migrations done"

echo "🚀 Starting Trackly API..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
