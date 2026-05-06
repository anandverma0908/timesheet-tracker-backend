"""Run before alembic on a fresh DB: creates all ORM-defined tables then stamps."""
import sys
import traceback

try:
    import app.models  # noqa — registers all ORM models with Base.metadata
    from app.core.database import Base, engine

    print("Connecting to database...")
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    print("Connection OK.")

    print("Running create_all...")
    Base.metadata.create_all(bind=engine)
    print("Base tables ready.")

except Exception as e:
    print(f"ERROR in init_db: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)
