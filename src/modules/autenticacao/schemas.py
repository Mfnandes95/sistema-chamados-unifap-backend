from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Perfil(StrEnum):
    SOLICITANTE = "SOLICITANTE"
    EXECUTOR = "EXECUTOR"
    GESTOR = "GESTOR"
    ADMIN = "ADMIN"


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(_Entrada):
    matricula: str = Field(pattern=r"^\d{6,12}$", examples=["20230001"])
    senha: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em_segundos: int
    perfil: Perfil
    deve_redefinir_senha: bool = False
    usando_senha_padrao: bool = False


class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    matricula: str
    nome: str
    email: str
    perfil: Perfil
    vinculo_ativo: bool
    setor: str | None = None
    deve_redefinir_senha: bool = False
    sessao_versao: int = Field(default=1, exclude=True)


class CriarUsuarioRequest(_Entrada):
    matricula: str = Field(pattern=r"^\d{6,12}$", examples=["20240099"])
    nome: str = Field(min_length=3, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)
    senha: str = Field(min_length=8, max_length=128)
    perfil: Perfil = Perfil.SOLICITANTE
    vinculo: Literal["discente", "docente", "tecnico_administrativo"] = "discente"
    vinculo_ativo: bool = True
    setor: str | None = Field(default=None, max_length=64)
    deve_redefinir_senha: bool = False


class RedefinirSenhaAdminRequest(_Entrada):
    nova_senha: str = Field(min_length=8, max_length=128)
    deve_redefinir_senha: bool = True


class AlterarPropriaSenhaRequest(_Entrada):
    senha_atual: str = Field(min_length=8, max_length=128)
    nova_senha: str = Field(min_length=10, max_length=128)


class EsqueciSenhaRequest(_Entrada):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)


class ConfirmarRedefinicaoSenhaRequest(_Entrada):
    token: str = Field(min_length=16, max_length=256)
    nova_senha: str = Field(min_length=10, max_length=128)


class MensagemResponse(BaseModel):
    mensagem: str
