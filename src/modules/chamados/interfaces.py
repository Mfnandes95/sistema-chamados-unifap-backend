"""Contratos públicos do módulo de chamados (únicos pontos de acesso de outros módulos)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.modules.autenticacao.schemas import UsuarioAutenticado
from src.modules.chamados.domain.avaliador_prioridade import CriteriosPrioridade
from src.modules.chamados.domain.entities import (
    Chamado,
    Comentario,
    Evidencia,
    Prioridade,
    RegistroAuditoria,
    StatusChamado,
)
from src.modules.chamados.domain.value_objects import Protocolo
from src.modules.chamados.schemas import AbrirChamadoRequest

LIMITE_PAGINA_MAXIMO = 100


@dataclass(frozen=True, slots=True)
class FiltroChamados:
    status: StatusChamado | None = None
    status_excluidos: frozenset[StatusChamado] = frozenset()
    prioridade: Prioridade | None = None
    solicitante_id: str | None = None
    executor_id: str | None = None
    local_id: str | None = None
    categoria_id: str | None = None
    criado_de: datetime | None = None
    criado_ate: datetime | None = None


@dataclass(frozen=True, slots=True)
class Pagina:
    limite: int = 50
    deslocamento: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limite <= LIMITE_PAGINA_MAXIMO or self.deslocamento < 0:
            raise ValueError("Paginação inválida.")

    def aplicar(self, itens: list[Chamado]) -> list[Chamado]:
        return itens[self.deslocamento:self.deslocamento + self.limite]


@dataclass(frozen=True, slots=True)
class ChamadoSnapshot:
    """Projeção imutável e somente-leitura para relatórios (RF15)."""

    protocolo: str
    local_id: str
    categoria_id: str
    equipamento: str | None
    status: StatusChamado
    prioridade: Prioridade
    criado_em: datetime
    resolvido_em: datetime | None
    nota_avaliacao: int | None
    reaberturas: int


class IRepositorioChamado(Protocol):
    def salvar(self, chamado: Chamado, versao_esperada: int) -> None:
        """Grava somente se a versão persistida == `versao_esperada` (0 = inserção).

        Lança ConflitoConcorrencia caso contrário (equivale a
        `UPDATE ... WHERE versao = :versao_esperada` no banco real).
        """
        ...

    def obter(self, protocolo: str) -> Chamado | None: ...

    def listar(self, filtro: FiltroChamados) -> list[Chamado]: ...

    def registrar_auditoria(self, registro: RegistroAuditoria) -> None: ...

    def listar_auditoria(self, protocolo: str) -> tuple[RegistroAuditoria, ...]: ...


class IAvaliadorPrioridade(Protocol):
    def avaliar(self, criterios: CriteriosPrioridade) -> Prioridade: ...


class IGeradorProtocolo(Protocol):
    def gerar(self) -> Protocolo: ...


class IOperacoesTriagem(Protocol):
    def listar_fila(self, filtro: FiltroChamados, pagina: Pagina = ...) -> list[Chamado]: ...

    def atribuir(self, protocolo: str, executor_id: str, ator: UsuarioAutenticado,
                 observacao: str | None) -> Chamado: ...

    def reencaminhar(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado: ...


class IRegistroEvidencias(Protocol):
    def verificar_pode_anexar(self, protocolo: str, ator: UsuarioAutenticado) -> None: ...

    def registrar_evidencia(self, protocolo: str, evidencia: Evidencia,
                            ator: UsuarioAutenticado) -> None: ...

    def obter_evidencia(self, protocolo: str, evidencia_id: str,
                        ator: UsuarioAutenticado) -> Evidencia: ...


class IConsultaChamados(Protocol):
    def snapshots(self, filtro: FiltroChamados) -> Sequence[ChamadoSnapshot]: ...


class IGestorChamados(IOperacoesTriagem, IRegistroEvidencias, IConsultaChamados, Protocol):
    def abrir_chamado(self, dados: AbrirChamadoRequest, ator: UsuarioAutenticado) -> Chamado: ...

    def obter_chamado(self, protocolo: str, ator: UsuarioAutenticado) -> Chamado: ...

    def listar_chamados(self, filtro: FiltroChamados, ator: UsuarioAutenticado,
                        pagina: Pagina = ...) -> list[Chamado]: ...

    def comentar(self, protocolo: str, texto: str, interno: bool,
                 ator: UsuarioAutenticado) -> Comentario: ...

    def iniciar_atendimento(self, protocolo: str, ator: UsuarioAutenticado) -> Chamado: ...

    def resolver(self, protocolo: str, solucao: str, ator: UsuarioAutenticado) -> Chamado: ...

    def avaliar(self, protocolo: str, nota: int, comentario: str | None,
                ator: UsuarioAutenticado) -> Chamado: ...

    def reabrir(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado: ...

    def cancelar(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado: ...

    def historico(self, protocolo: str,
                  ator: UsuarioAutenticado) -> tuple[RegistroAuditoria, ...]: ...

    def fechar_resolvidos_expirados(self) -> int: ...
