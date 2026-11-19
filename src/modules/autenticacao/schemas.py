from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Perfil(StrEnum):
    SOLICITANTE = "SOLICITANTE"
    EXECUTOR = "EXECUTOR"
    GESTOR = "GESTOR"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    matricula: str = Field(pattern=r"^\d{6,12}$", examples=["20230001"])
    senha: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em_segundos: int
    perfil: Perfil


class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    matricula: str
    nome: str
    email: str
    perfil: Perfil
    vinculo_ativo: bool
    setor: str | None = None
