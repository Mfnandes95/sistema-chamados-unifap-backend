"""CRC 4: InMemoryRepositorioChamado com trilha de auditoria append-only."""

import copy
import threading

from src.core.exceptions import ConflitoConcorrencia
from src.modules.chamados.domain.entities import Chamado, RegistroAuditoria
from src.modules.chamados.interfaces import FiltroChamados


def _atende(c: Chamado, f: FiltroChamados) -> bool:
    return (
        (f.status is None or c.status is f.status)
        and c.status not in f.status_excluidos
        and (f.prioridade is None or c.prioridade is f.prioridade)
        and (f.solicitante_id is None or c.solicitante_id == f.solicitante_id)
        and (f.executor_id is None or c.executor_id == f.executor_id)
        and (f.local_id is None or c.local_id == f.local_id)
        and (f.categoria_id is None or c.categoria_id == f.categoria_id)
        and (f.criado_de is None or c.criado_em >= f.criado_de)
        and (f.criado_ate is None or c.criado_em <= f.criado_ate)
    )


class InMemoryRepositorioChamado:
    """Armazena cópias profundas para emular a fronteira de persistência real."""

    def __init__(self) -> None:
        self._chamados: dict[str, Chamado] = {}
        self._auditoria: list[RegistroAuditoria] = []
        self._lock = threading.RLock()

    def salvar(self, chamado: Chamado, versao_esperada: int) -> None:
        with self._lock:
            atual = self._chamados.get(chamado.protocolo)
            versao_atual = atual.versao if atual is not None else 0
            if versao_atual != versao_esperada:  # V05 / V06
                raise ConflitoConcorrencia(
                    f"Chamado {chamado.protocolo} foi alterado por outra operação. "
                    "Recarregue e tente novamente.")
            if chamado.versao <= versao_esperada:
                raise ValueError("A versão do chamado deve ser incrementada antes de salvar.")
            self._chamados[chamado.protocolo] = copy.deepcopy(chamado)

    def obter(self, protocolo: str) -> Chamado | None:
        with self._lock:
            c = self._chamados.get(protocolo)
            return copy.deepcopy(c) if c is not None else None

    def listar(self, filtro: FiltroChamados) -> list[Chamado]:
        with self._lock:
            return [copy.deepcopy(c) for c in self._chamados.values() if _atende(c, filtro)]

    def registrar_auditoria(self, registro: RegistroAuditoria) -> None:
        with self._lock:
            self._auditoria.append(registro)  # append-only: sem update/delete

    def listar_auditoria(self, protocolo: str) -> tuple[RegistroAuditoria, ...]:
        with self._lock:
            return tuple(r for r in self._auditoria if r.protocolo == protocolo)
