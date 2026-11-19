from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado


class IAutenticadorInstitucional(Protocol):
    """Contrato de autenticação contra a base institucional (RF01, D03)."""

    def autenticar(self, matricula: str, senha: str) -> UsuarioAutenticado: ...

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None: ...

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]: ...


class ILimitadorTentativas(Protocol):
    """Janela deslizante de falhas por chave (conta ou IP) — RNF04 / V02."""

    def verificar(self, chave: str, maximo: int) -> None: ...

    def registrar_falha(self, chave: str) -> None: ...

    def limpar(self, chave: str) -> None: ...


class IListaRevogacao(Protocol):
    """Denylist de `jti` até a expiração natural do token — V09."""

    def revogar(self, jti: str, expira_em: datetime) -> None: ...

    def esta_revogado(self, jti: str) -> bool: ...
