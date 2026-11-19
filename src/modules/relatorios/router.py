from typing import Annotated

from fastapi import APIRouter, Query, Response

from src.core.container import ContainerDep
from src.modules.autenticacao.dependencies import GestorOuAdmin
from src.modules.relatorios.interfaces import (
    FiltroRelatorioDTO,
    FormatoExportacao,
    RelatorioHistoricoDTO,
)

class FiltroExportacaoDTO(FiltroRelatorioDTO):
    formato: FormatoExportacao = FormatoExportacao.CSV


router = APIRouter(prefix="/api/v1/relatorios", tags=["relatórios"])


@router.get("/historico", response_model=RelatorioHistoricoDTO)
def historico(_: GestorOuAdmin, c: ContainerDep,
              filtro: Annotated[FiltroRelatorioDTO, Query()]) -> RelatorioHistoricoDTO:
    return c.relatorios.gerar_historico(filtro)


@router.get("/exportar")
def exportar(_: GestorOuAdmin, c: ContainerDep,
             q: Annotated[FiltroExportacaoDTO, Query()]) -> Response:
    filtro = FiltroRelatorioDTO.model_validate(q.model_dump(exclude={"formato"}))
    arquivo = c.relatorios.exportar(filtro, q.formato)
    return Response(content=arquivo.conteudo, media_type=arquivo.media_type,
                    headers={"Content-Disposition": f'attachment; filename="{arquivo.nome}"'})
