"""Container de dependências tipado apenas por Protocols (composition root em main.py)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import BackgroundTasks, Depends, Request

from src.core.config import Settings

if TYPE_CHECKING:
    from src.modules.autenticacao.interfaces import (
        IAutenticadorInstitucional,
        ILimitadorTentativas,
        IListaRevogacao,
    )
    from src.modules.catalogo_locais.interfaces import IValidadorCatalogo
    from src.modules.chamados.interfaces import IGestorChamados
    from src.modules.evidencias.interfaces import IServicoEvidencias
    from src.modules.notificacoes.interfaces import IServicoNotificacao
    from src.modules.relatorios.interfaces import IServicoRelatorios
    from src.modules.triagem.interfaces import IServicoTriagem


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    autenticador: IAutenticadorInstitucional
    limitador_login: ILimitadorTentativas
    revogacao: IListaRevogacao
    catalogo: IValidadorCatalogo
    gestor_chamados: IGestorChamados
    triagem: IServicoTriagem
    evidencias: IServicoEvidencias
    notificacoes: IServicoNotificacao
    relatorios: IServicoRelatorios


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]


def agendar_notificacoes(background_tasks: BackgroundTasks, container: ContainerDep) -> None:
    """D07/ADR-01: despacha notificações pendentes após o envio da resposta HTTP."""
    background_tasks.add_task(container.notificacoes.processar_pendentes)
