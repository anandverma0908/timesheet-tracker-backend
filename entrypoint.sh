#!/bin/bash
set -e

echo "⏳ Waiting for postgres..."
until pg_isready -h "${PGHOST:-postgres}" -U "${PGUSER:-trackly}" > /dev/null 2>&1; do
  sleep 1
done
echo "✅ Postgres ready"

echo "🔄 Running migrations..."
alembic upgrade head
echo "✅ Migrations done"

echo "🚀 Starting Trackly API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
