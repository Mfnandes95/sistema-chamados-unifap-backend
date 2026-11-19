from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado


class TipoEvento(StrEnum):
    CHAMADO_ABERTO = "CHAMADO_ABERTO"
    CHAMADO_ATRIBUIDO = "CHAMADO_ATRIBUIDO"
    STATUS_ALTERADO = "STATUS_ALTERADO"
    COMENTARIO_ADICIONADO = "COMENTARIO_ADICIONADO"
    CHAMADO_RESOLVIDO = "CHAMADO_RESOLVIDO"
    CHAMADO_REABERTO = "CHAMADO_REABERTO"
    CHAMADO_REENCAMINHADO = "CHAMADO_REENCAMINHADO"
    CHAMADO_FECHADO = "CHAMADO_FECHADO"


GRUPO_GESTORES = "@GESTORES"
"""Referência simbólica resolvida no despacho para todos os gestores ativos."""


@dataclass(frozen=True, slots=True)
class EventoNotificacao:
    tipo: TipoEvento
    protocolo: str
    destinatarios: tuple[str, ...]
    """IDs de usuário ou grupos simbólicos (ex.: GRUPO_GESTORES)."""
    mensagem: str
    ocorrido_em: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Destinatario:
    id: str
    email: str


@dataclass(frozen=True, slots=True)
class FalhaEntrega:
    canal: str
    destinatario: str
    protocolo: str
    erro: str


class ICanalNotificacao(Protocol):
    @property
    def nome(self) -> str: ...

    async def enviar(self, evento: EventoNotificacao, destinatario: Destinatario) -> None: ...


class IFonteUsuarios(Protocol):
    """Subconjunto do diretório institucional necessário para resolver destinatários."""

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None: ...

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]: ...


class IDiretorioDestinatarios(Protocol):
    def resolver(self, referencias: Sequence[str]) -> Sequence[Destinatario]: ...


class IPublicadorEventos(Protocol):
    """Porta usada pelo domínio: publicar é O(1) e nunca bloqueia (RN03)."""

    def publicar(self, evento: EventoNotificacao) -> None: ...


class IServicoNotificacao(IPublicadorEventos, Protocol):
    async def processar_pendentes(self) -> int: ...

    def quantidade_pendentes(self) -> int: ...

    def falhas(self) -> Sequence[FalhaEntrega]: ...
