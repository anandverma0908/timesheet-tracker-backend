#!/bin/bash
set -e

# Parse host and user from DATABASE_URL if PGHOST is not explicitly set
if [ -z "${PGHOST}" ] && [ -n "${DATABASE_URL}" ]; then
  export PGHOST=$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')
  export PGUSER=$(echo "$DATABASE_URL" | sed -E 's|.*://([^:]+):.*|\1|')
fi

echo "⏳ Waiting for postgres at ${PGHOST}..."
until pg_isready -h "${PGHOST:-postgres}" -U "${PGUSER:-trackly}" > /dev/null 2>&1; do
  sleep 1
done
echo "✅ Postgres ready"

echo "🔄 Running migrations..."
alembic upgrade head
echo "✅ Migrations done"

echo "🚀 Starting Trackly API..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
