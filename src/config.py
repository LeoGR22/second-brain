from typing import Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_TOKEN = "dev-secret-token"
MIN_TOKEN_LENGTH = 32


class Settings(BaseSettings):
    port: int = 8080
    host: str = "0.0.0.0"

    # Token obrigatório para autenticar requisições no endpoint /mcp.
    # O valor padrão só é aceito no modo local (sqlite).
    auth_token: str = DEV_TOKEN

    # "firestore" para produção no GCP ou "sqlite" para testes locais
    storage_backend: Literal["firestore", "sqlite"] = "sqlite"

    # Firestore
    gcp_project_id: Optional[str] = None
    firestore_collection: str = "second_brain_memories"
    # Quantos documentos, no máximo, a busca textual examina (Firestore não tem busca full-text)
    firestore_max_scan: int = 2000
    # Para testes locais com o emulador (ex: localhost:8085). Nunca defina em produção.
    firestore_emulator_host: Optional[str] = None

    # SQLite
    sqlite_db_path: str = "local_storage/memories.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_production_token(self) -> "Settings":
        """Impede que o servidor suba em produção protegido por um token fraco ou público."""
        if self.storage_backend == "firestore":
            if self.auth_token == DEV_TOKEN or len(self.auth_token) < MIN_TOKEN_LENGTH:
                raise ValueError(
                    f"AUTH_TOKEN ausente ou fraco para o modo firestore. "
                    f"Use um token com pelo menos {MIN_TOKEN_LENGTH} caracteres "
                    f"(ex: openssl rand -hex 32)."
                )
        return self


settings = Settings()
