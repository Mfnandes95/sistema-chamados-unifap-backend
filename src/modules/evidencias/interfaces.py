from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.modules.autenticacao.schemas import UsuarioAutenticado

LeitorBytes = Callable[[int], Awaitable[bytes]]


class EvidenciaDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    protocolo: str
    nome_arquivo: str
    content_type: str
    tamanho_bytes: int
    enviado_em: datetime


class ImportarDriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=20, max_length=512)
    nome_arquivo: str | None = Field(default=None, max_length=200)


class ArquivoEvidencia(BaseModel):
    model_config = ConfigDict(frozen=True)

    caminho: Path | None = None
    conteudo: bytes | None = None
    nome_arquivo: str
    content_type: str


class IServicoEvidencias(Protocol):
    async def anexar(self, protocolo: str, nome_arquivo: str, content_type: str,
                     leitor: LeitorBytes, ator: UsuarioAutenticado) -> EvidenciaDTO: ...

    async def anexar_google_drive(
        self, protocolo: str, url: str, nome_arquivo: str | None, ator: UsuarioAutenticado
    ) -> EvidenciaDTO: ...

    def obter_arquivo(
        self, protocolo: str, evidencia_id: str, ator: UsuarioAutenticado
    ) -> ArquivoEvidencia: ...
