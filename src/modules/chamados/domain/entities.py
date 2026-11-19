from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from src.modules.autenticacao.schemas import Perfil


class StatusChamado(StrEnum):
    ABERTO = "ABERTO"
    ATRIBUIDO = "ATRIBUIDO"
    EM_ATENDIMENTO = "EM_ATENDIMENTO"
    RESOLVIDO = "RESOLVIDO"
    REABERTO = "REABERTO"
    FECHADO = "FECHADO"
    CANCELADO = "CANCELADO"


class Prioridade(StrEnum):
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"

    @property
    def peso(self) -> int:
        return list(Prioridade).index(self)


@dataclass(frozen=True, slots=True)
class Comentario:
    id: str
    autor_id: str
    autor_perfil: Perfil
    texto: str
    interno: bool
    criado_em: datetime


@dataclass(frozen=True, slots=True)
class Avaliacao:
    nota: int
    comentario: str | None
    criado_em: datetime

    def __post_init__(self) -> None:
        if not 1 <= self.nota <= 5:
            raise ValueError("Nota deve estar entre 1 e 5.")


@dataclass(frozen=True, slots=True)
class Evidencia:
    id: str
    nome_arquivo: str
    content_type: str
    tamanho_bytes: int
    caminho: str
    enviado_por: str
    enviado_em: datetime


@dataclass(frozen=True, slots=True)
class RegistroAuditoria:
    id: str
    protocolo: str
    ator_id: str
    acao: str
    status_anterior: StatusChamado | None
    status_novo: StatusChamado
    detalhe: str | None
    registrado_em: datetime
    visivel_solicitante: bool = True


@dataclass(slots=True)
class Chamado:
    protocolo: str
    titulo: str
    descricao: str
    solicitante_id: str
    local_id: str
    categoria_id: str
    equipamento: str | None
    prioridade: Prioridade
    criado_em: datetime
    atualizado_em: datetime
    impacta_aulas: bool = False
    pessoas_afetadas: int = 0
    status: StatusChamado = StatusChamado.ABERTO
    executor_id: str | None = None
    comentarios: list[Comentario] = field(default_factory=list)
    evidencias: list[Evidencia] = field(default_factory=list)
    avaliacao: Avaliacao | None = None
    resolvido_em: datetime | None = None
    fechado_em: datetime | None = None
    reaberturas: int = 0
    versao: int = 0
    """Controle de concorrência otimista (V05). 0 = ainda não persistido."""
