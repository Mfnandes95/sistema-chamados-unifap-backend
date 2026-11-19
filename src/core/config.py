"""Configuração centralizada via Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SEGREDO_DESENVOLVIMENTO = "dev-secret-nao-usar-em-producao-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UNIFAP_", env_file=".env", extra="ignore", frozen=True
    )

    ambiente: Literal["desenvolvimento", "teste", "producao"] = "desenvolvimento"
    nome_app: str = "Sistema de Chamados UNIFAP"

    # --- Sessão / JWT (V01, V09)
    jwt_secret: str = Field(default=SEGREDO_DESENVOLVIMENTO, min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_audience: str = "unifap-chamados-api"
    jwt_expire_minutes: int = Field(default=60, ge=1, le=1440)

    # --- Proteção contra força bruta (V02)
    login_max_tentativas_conta: int = Field(default=5, ge=1)
    login_max_tentativas_ip: int = Field(default=20, ge=1)
    login_janela_minutos: int = Field(default=15, ge=1)

    # --- HTTP (V04, V16)
    cors_origins: list[str] = ["http://localhost:5173"]
    max_corpo_bytes: int = Field(default=1024 * 1024, ge=1024)

    # --- Evidências (RF03, V13)
    upload_dir: Path = Path("./uploads")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_evidencias_por_chamado: int = Field(default=10, ge=1)

    # --- Regras de negócio
    prazo_reabertura_dias: int = Field(default=7, ge=0)
    max_reaberturas: int = Field(default=3, ge=0)
    intervalo_manutencao_segundos: int = Field(default=300, ge=5)

    @property
    def producao(self) -> bool:
        return self.ambiente == "producao"

    @model_validator(mode="after")
    def _validar_producao(self) -> "Settings":
        if self.producao:
            if self.jwt_secret == SEGREDO_DESENVOLVIMENTO:
                raise ValueError("UNIFAP_JWT_SECRET precisa ser definido em produção.")
            if "*" in self.cors_origins:
                raise ValueError("CORS com '*' não é permitido em produção.")
        return self


@lru_cache
def obter_settings() -> Settings:
    return Settings()
