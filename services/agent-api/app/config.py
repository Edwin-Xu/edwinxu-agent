from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    db_path: str
    trace_dir: str
    anthropic_base_url: str | None
    anthropic_api_key: str | None
    anthropic_auth_token: str | None
    anthropic_model: str
    api_timeout_ms: int


def get_settings() -> Settings:
    db_path = os.getenv("AGENT_DB_PATH", "../../data/sqlite/agent.db")
    trace_dir = os.getenv("AGENT_TRACE_DIR", "../../artifacts/traces")
    anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or None
    anthropic_auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN") or None
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    api_timeout_ms = int(os.getenv("API_TIMEOUT_MS", "300000"))
    return Settings(
        db_path=db_path,
        trace_dir=trace_dir,
        anthropic_base_url=anthropic_base_url,
        anthropic_api_key=anthropic_api_key,
        anthropic_auth_token=anthropic_auth_token,
        anthropic_model=anthropic_model,
        api_timeout_ms=api_timeout_ms,
    )

