"""
Run before alembic on deploy:
- Fresh DB: create_all() builds schema from ORM, then stamp alembic to head (skip migrations).
- Existing DB: skip create_all, let alembic upgrade head run normally.
"""
import sys
import traceback
from sqlalchemy import text, inspect

try:
    import app.models  # noqa — registers all ORM models with Base.metadata
    from app.core.database import Base, engine

    print("Connecting to database...")
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connection OK.")

    # Check if this is a fresh DB (alembic_version table doesn't exist yet)
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    is_fresh = "alembic_version" not in existing_tables

    if is_fresh:
        print("Fresh database detected — running create_all...")
        Base.metadata.create_all(bind=engine)
        print("Base tables created.")

        # Stamp to head so alembic upgrade head is a no-op
        import subprocess, os
        env = os.environ.copy()
        result = subprocess.run(
            ["alembic", "stamp", "head"],
            env=env,
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)
        print("Alembic stamped to head.")
    else:
        print(f"Existing database detected ({len(existing_tables)} tables) — skipping create_all.")

except Exception as e:
    print(f"ERROR in init_db: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)
