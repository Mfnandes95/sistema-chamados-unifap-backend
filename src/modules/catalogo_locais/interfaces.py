from collections.abc import Sequence
from typing import Protocol

from src.modules.catalogo_locais.schemas import CategoriaDTO, LocalDTO, TipoLocal


class IValidadorCatalogo(Protocol):
    """Fonte da verdade da restrição de domínio RD01 (locais/categorias válidos)."""

    def validar_local(self, local_id: str) -> LocalDTO: ...

    def validar_categoria(self, categoria_id: str, equipamento: str | None) -> CategoriaDTO: ...

    def listar_locais(self, bloco: str | None = None,
                      tipo: TipoLocal | None = None) -> Sequence[LocalDTO]: ...

    def listar_categorias(self) -> Sequence[CategoriaDTO]: ...
