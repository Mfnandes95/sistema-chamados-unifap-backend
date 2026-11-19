from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from src.core.container import ContainerDep, agendar_notificacoes
from src.modules.autenticacao.dependencies import (
    Executor,
    SolicitanteAtivo,
    UsuarioAtivo,
    UsuarioAtual,
)
from src.modules.chamados.interfaces import FiltroChamados, Pagina
from src.modules.chamados.schemas import (
    PROTOCOLO_REGEX,
    AbrirChamadoRequest,
    AvaliacaoRequest,
    ChamadoResponse,
    ChamadoResumoResponse,
    ComentarioRequest,
    ComentarioResponse,
    FiltroChamadosQuery,
    MotivoRequest,
    RegistroAuditoriaResponse,
    ResolverRequest,
)

router = APIRouter(prefix="/api/v1/chamados", tags=["chamados"],
                   dependencies=[Depends(agendar_notificacoes)])

ProtocoloPath = Annotated[str, Path(pattern=PROTOCOLO_REGEX)]


@router.post("", response_model=ChamadoResponse, status_code=status.HTTP_201_CREATED)
def abrir(dados: AbrirChamadoRequest, ator: SolicitanteAtivo,
          c: ContainerDep) -> ChamadoResponse:
    chamado = c.gestor_chamados.abrir_chamado(dados, ator)
    return ChamadoResponse.de_entidade(chamado, ator.perfil)


@router.get("", response_model=list[ChamadoResumoResponse])
def listar(ator: UsuarioAtual, c: ContainerDep,
           q: Annotated[FiltroChamadosQuery, Query()]) -> list[ChamadoResumoResponse]:
    filtro = FiltroChamados(status=q.status, prioridade=q.prioridade, local_id=q.local_id,
                            categoria_id=q.categoria_id)
    pagina = Pagina(limite=q.limite, deslocamento=q.deslocamento)
    return [ChamadoResumoResponse.model_validate(x)
            for x in c.gestor_chamados.listar_chamados(filtro, ator, pagina)]


@router.get("/{protocolo}", response_model=ChamadoResponse)
def detalhar(protocolo: ProtocoloPath, ator: UsuarioAtual, c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(c.gestor_chamados.obter_chamado(protocolo, ator),
                                       ator.perfil)


@router.post("/{protocolo}/comentarios", response_model=ComentarioResponse,
             status_code=status.HTTP_201_CREATED)
def comentar(protocolo: ProtocoloPath, dados: ComentarioRequest, ator: UsuarioAtivo,
             c: ContainerDep) -> ComentarioResponse:
    com = c.gestor_chamados.comentar(protocolo, dados.texto, dados.interno, ator)
    return ComentarioResponse.model_validate(com)


@router.post("/{protocolo}/iniciar", response_model=ChamadoResponse)
def iniciar(protocolo: ProtocoloPath, ator: Executor, c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(c.gestor_chamados.iniciar_atendimento(protocolo, ator),
                                       ator.perfil)


@router.post("/{protocolo}/resolver", response_model=ChamadoResponse)
def resolver(protocolo: ProtocoloPath, dados: ResolverRequest, ator: Executor,
             c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(
        c.gestor_chamados.resolver(protocolo, dados.solucao, ator), ator.perfil)


@router.post("/{protocolo}/avaliacao", response_model=ChamadoResponse)
def avaliar(protocolo: ProtocoloPath, dados: AvaliacaoRequest, ator: SolicitanteAtivo,
            c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(
        c.gestor_chamados.avaliar(protocolo, dados.nota, dados.comentario, ator), ator.perfil)


@router.post("/{protocolo}/reabrir", response_model=ChamadoResponse)
def reabrir(protocolo: ProtocoloPath, dados: MotivoRequest, ator: SolicitanteAtivo,
            c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(
        c.gestor_chamados.reabrir(protocolo, dados.motivo, ator), ator.perfil)


@router.post("/{protocolo}/cancelar", response_model=ChamadoResponse)
def cancelar(protocolo: ProtocoloPath, dados: MotivoRequest, ator: UsuarioAtivo,
             c: ContainerDep) -> ChamadoResponse:
    return ChamadoResponse.de_entidade(
        c.gestor_chamados.cancelar(protocolo, dados.motivo, ator), ator.perfil)


@router.get("/{protocolo}/historico", response_model=list[RegistroAuditoriaResponse])
def historico(protocolo: ProtocoloPath, ator: UsuarioAtual,
              c: ContainerDep) -> list[RegistroAuditoriaResponse]:
    return RegistroAuditoriaResponse.lista(c.gestor_chamados.historico(protocolo, ator))
