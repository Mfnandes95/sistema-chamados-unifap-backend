from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from src.core.container import ContainerDep, agendar_notificacoes
from src.modules.autenticacao.dependencies import EquipeTecnica, Executor, Gestor
from src.modules.chamados.schemas import PROTOCOLO_REGEX, ChamadoResumoResponse
from src.modules.triagem.schemas import AtribuicaoDTO, FiltroFilaDTO, ReencaminhamentoDTO

router = APIRouter(prefix="/api/v1/triagem", tags=["triagem"],
                   dependencies=[Depends(agendar_notificacoes)])

ProtocoloPath = Annotated[str, Path(pattern=PROTOCOLO_REGEX)]


@router.get("/fila", response_model=list[ChamadoResumoResponse])
def fila(ator: EquipeTecnica, c: ContainerDep,
         filtro: Annotated[FiltroFilaDTO, Query()]) -> list[ChamadoResumoResponse]:
    return [ChamadoResumoResponse.model_validate(x) for x in c.triagem.listar_fila(filtro, ator)]


@router.post("/{protocolo}/atribuir", response_model=ChamadoResumoResponse)
def atribuir(protocolo: ProtocoloPath, dados: AtribuicaoDTO, ator: Gestor,
             c: ContainerDep) -> ChamadoResumoResponse:
    return ChamadoResumoResponse.model_validate(c.triagem.atribuir(protocolo, dados, ator))


@router.post("/{protocolo}/reencaminhar", response_model=ChamadoResumoResponse)
def reencaminhar(protocolo: ProtocoloPath, dados: ReencaminhamentoDTO, ator: Executor,
                 c: ContainerDep) -> ChamadoResumoResponse:
    return ChamadoResumoResponse.model_validate(c.triagem.reencaminhar(protocolo, dados, ator))
