"""Máquina de estados finitos do chamado."""

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Final

from src.core.exceptions import TransicaoInvalida
from src.modules.chamados.domain.entities import Chamado, StatusChamado

S = StatusChamado

TRANSICOES: Final[Mapping[StatusChamado, frozenset[StatusChamado]]] = MappingProxyType({
    S.ABERTO: frozenset({S.ATRIBUIDO, S.CANCELADO}),
    S.ATRIBUIDO: frozenset({S.ATRIBUIDO, S.EM_ATENDIMENTO, S.ABERTO, S.CANCELADO}),
    S.EM_ATENDIMENTO: frozenset({S.RESOLVIDO, S.ABERTO}),
    S.RESOLVIDO: frozenset({S.FECHADO, S.REABERTO}),
    S.REABERTO: frozenset({S.EM_ATENDIMENTO, S.ATRIBUIDO, S.ABERTO}),
    S.FECHADO: frozenset(),
    S.CANCELADO: frozenset(),
})

ESTADOS_TERMINAIS: Final = frozenset(s for s, d in TRANSICOES.items() if not d)


class MaquinaEstadosChamado:
    @staticmethod
    def pode_transitar(atual: StatusChamado, novo: StatusChamado) -> bool:
        return novo in TRANSICOES[atual]

    @classmethod
    def validar(cls, atual: StatusChamado, novo: StatusChamado) -> None:
        if not cls.pode_transitar(atual, novo):
            raise TransicaoInvalida(f"Transição {atual.value} -> {novo.value} não permitida.")

    @classmethod
    def transitar(cls, chamado: Chamado, novo: StatusChamado, quando: datetime) -> StatusChamado:
        anterior = chamado.status
        cls.validar(anterior, novo)
        chamado.status = novo
        chamado.atualizado_em = quando
        return anterior
