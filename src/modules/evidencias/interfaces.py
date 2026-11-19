from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

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


class IServicoEvidencias(Protocol):
    async def anexar(self, protocolo: str, nome_arquivo: str, content_type: str,
                     leitor: LeitorBytes, ator: UsuarioAutenticado) -> EvidenciaDTO: ...
