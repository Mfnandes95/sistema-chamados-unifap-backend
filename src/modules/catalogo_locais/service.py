"""InMemoryCatalogoAdapter: catálogo seed com validação estrita RD01."""

from collections.abc import Sequence

from src.core.exceptions import ValidacaoDominio
from src.modules.catalogo_locais.schemas import CategoriaDTO, LocalDTO, TipoLocal


def locais_seed() -> list[LocalDTO]:
    return [
        LocalDTO(id="BL1-T-S101", bloco="BLOCO-1", andar=0, nome="Sala 101", tipo=TipoLocal.SALA),
        LocalDTO(id="BL1-1-S201", bloco="BLOCO-1", andar=1, nome="Sala 201", tipo=TipoLocal.SALA),
        LocalDTO(id="BL1-1-LAB1", bloco="BLOCO-1", andar=1, nome="Lab. Informática 1",
                 tipo=TipoLocal.LABORATORIO),
        LocalDTO(id="BL2-T-AUD", bloco="BLOCO-2", andar=0, nome="Auditório Central",
                 tipo=TipoLocal.AUDITORIO),
        LocalDTO(id="BL2-1-LABQ", bloco="BLOCO-2", andar=1, nome="Lab. Química",
                 tipo=TipoLocal.LABORATORIO),
        LocalDTO(id="BL2-T-HALL", bloco="BLOCO-2", andar=0, nome="Hall de Entrada",
                 tipo=TipoLocal.AREA_COMUM),
    ]


def categorias_seed() -> list[CategoriaDTO]:
    return [
        CategoriaDTO(id="ELETRICA", nome="Elétrica", criticidade=3,
                     equipamentos=("TOMADA", "LAMPADA", "DISJUNTOR")),
        CategoriaDTO(id="CLIMATIZACAO", nome="Climatização", criticidade=2,
                     equipamentos=("AR_CONDICIONADO", "VENTILADOR")),
        CategoriaDTO(id="TI", nome="Tecnologia da Informação", criticidade=2,
                     equipamentos=("PROJETOR", "COMPUTADOR", "REDE")),
        CategoriaDTO(id="MOBILIARIO", nome="Mobiliário", criticidade=1,
                     equipamentos=("CADEIRA", "MESA", "QUADRO")),
    ]


class InMemoryCatalogoAdapter:
    def __init__(self, locais: Sequence[LocalDTO] | None = None,
                 categorias: Sequence[CategoriaDTO] | None = None) -> None:
        self._locais = {x.id: x for x in (locais if locais is not None else locais_seed())}
        self._categorias = {
            x.id: x for x in (categorias if categorias is not None else categorias_seed())
        }

    def validar_local(self, local_id: str) -> LocalDTO:
        local = self._locais.get(local_id)
        if local is None:
            raise ValidacaoDominio(f"RD01: local '{local_id}' não pertence ao catálogo.")
        return local

    def validar_categoria(self, categoria_id: str, equipamento: str | None) -> CategoriaDTO:
        categoria = self._categorias.get(categoria_id)
        if categoria is None:
            raise ValidacaoDominio(f"RD01: categoria '{categoria_id}' inexistente.")
        if equipamento is not None and equipamento not in categoria.equipamentos:
            raise ValidacaoDominio(
                f"RD01: equipamento '{equipamento}' não pertence à categoria '{categoria_id}'."
            )
        return categoria

    def listar_locais(self, bloco: str | None = None,
                      tipo: TipoLocal | None = None) -> Sequence[LocalDTO]:
        return tuple(
            x for x in self._locais.values()
            if (bloco is None or x.bloco == bloco) and (tipo is None or x.tipo is tipo)
        )

    def listar_categorias(self) -> Sequence[CategoriaDTO]:
        return tuple(self._categorias.values())
