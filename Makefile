.PHONY: run dev migrate seed test lint

# ── Dev ───────────────────────────────────────────────────────────────────────

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn app.main:app --reload --port 8000

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(msg)"

migrate-down:
	alembic downgrade -1

# ── Seed data ─────────────────────────────────────────────────────────────────

seed:
	python seeds/seed_all.py

seed-tickets:
	python seeds/seed_tickets.py

seed-wiki:
	python seeds/seed_wiki.py

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	ruff check app/ --fix

format:
	ruff format app/

# ── Docker ───────────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api

# ── Helpers ───────────────────────────────────────────────────────────────────

nova-status:
	curl -s http://localhost:8000/api/nova/status | python -m json.tool

health:
	curl -s http://localhost:8000/api/health | python -m json.tool
