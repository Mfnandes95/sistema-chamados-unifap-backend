from itertools import groupby

from fastapi import APIRouter

from src.core.container import ContainerDep
from src.modules.autenticacao.dependencies import UsuarioAtual
from src.modules.catalogo_locais.schemas import (
    AndarDTO,
    BlocoDTO,
    CategoriaDTO,
    LocalDTO,
    TipoLocal,
)

router = APIRouter(prefix="/api/v1/catalogo", tags=["catálogo"])


@router.get("/locais", response_model=list[LocalDTO])
def listar_locais(_: UsuarioAtual, container: ContainerDep, bloco: str | None = None,
                  tipo: TipoLocal | None = None) -> list[LocalDTO]:
    return list(container.catalogo.listar_locais(bloco, tipo))


@router.get("/locais/arvore", response_model=list[BlocoDTO])
def arvore_locais(_: UsuarioAtual, container: ContainerDep) -> list[BlocoDTO]:
    locais = sorted(container.catalogo.listar_locais(), key=lambda x: (x.bloco, x.andar, x.nome))
    blocos: list[BlocoDTO] = []
    for bloco, itens_bloco in groupby(locais, key=lambda x: x.bloco):
        andares = [AndarDTO(andar=a, locais=list(itens))
                   for a, itens in groupby(itens_bloco, key=lambda x: x.andar)]
        blocos.append(BlocoDTO(bloco=bloco, andares=andares))
    return blocos


@router.get("/categorias", response_model=list[CategoriaDTO])
def listar_categorias(_: UsuarioAtual, container: ContainerDep) -> list[CategoriaDTO]:
    return list(container.catalogo.listar_categorias())
