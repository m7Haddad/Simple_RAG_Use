"""
Configuration. Everything is read once, at startup, from the .env file in the project root.
Real environment variables override it.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_LLM_MODEL = "deepseek/deepseek-v4.1-flash"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENROUTER_API_KEY"),
    )
    llm_model: str = DEFAULT_LLM_MODEL
    llm_timeout_s: float = 60.0

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    admin_password_hash: SecretStr | None = None
    jwt_secret: SecretStr | None = None
    token_ttl_minutes: int = 15
    login_max_attempts: int = 5
    login_window_s: int = 60

    frontend_origin: str = "http://localhost:5173,http://127.0.0.1:5173"
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")

    max_upload_mb: int = 25
    max_url_mb: int = 15
    url_timeout_s: float = 20.0
    max_sources_per_request: int = 20

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("llm_base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def llm_is_local(self) -> bool:
        host = urlparse(self.llm_base_url).hostname or ""
        return host in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}

    def llm_key_value(self) -> str | None:
        if self.llm_api_key and self.llm_api_key.get_secret_value().strip():
            return self.llm_api_key.get_secret_value().strip()
        # Local servers such as Ollama accept any key.
        return "local-no-key" if self.llm_is_local else None

    def secret_values(self) -> list[str]:
        secrets = [self.llm_api_key, self.admin_password_hash, self.jwt_secret]
        return [s.get_secret_value() for s in secrets if s and len(s.get_secret_value()) >= 6]


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
