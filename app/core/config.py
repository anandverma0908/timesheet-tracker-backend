"""
app/core/config.py — Centralised settings loaded from environment / .env file.

All configuration lives here. Import `settings` everywhere — never read
os.getenv() directly in route handlers or services.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "Trackly"
    app_version: str = "1.0.0"
    debug: bool = False
    dev_mode: bool = True
    frontend_url: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql://trackly:trackly@localhost:5432/trackly"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # ── NOVA Provider ────────────────────────────────────────────────────────
    # NOVA_PROVIDER=cerebras  → fast cloud inference (free tier)
    # NOVA_PROVIDER=ollama    → local Ollama (default)
    nova_provider: str = "ollama"

    # ── Ollama (local) ───────────────────────────────────────────────────────
    nova_model: str = "llama3.1:8b"
    nova_base_url: str = "http://ollama:11434"
    nova_temperature: float = 0.3
    nova_max_tokens: int = 1500
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Cerebras (cloud) ─────────────────────────────────────────────────────
    cerebras_api_key: str = ""
    cerebras_model: str = "llama3.1-8b"

    # ── File uploads ──────────────────────────────────────────────────────────
    upload_dir: str = "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB

    # ── GitHub integration ────────────────────────────────────────────────────
    github_token: str = ""          # Personal Access Token with repo scope
    github_repos: str = ""          # Comma-separated list: "org/repo1,org/repo2,org/repo3"

    # ── Jira sync ─────────────────────────────────────────────────────────────
    sync_interval_minutes: int = 30

    # ── Email (SMTP) ─────────────────────────────────────────────────────────
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_email: str = ""
    smtp_password: str = ""
    email_from_name: str = "Trackly"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Module-level singleton — import this everywhere
settings = get_settings()
