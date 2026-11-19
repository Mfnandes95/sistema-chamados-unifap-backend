from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from src.modules.autenticacao.schemas import CriarUsuarioRequest, Perfil, UsuarioAutenticado


class IAutenticadorInstitucional(Protocol):
    """Contrato de autenticação e gestão de usuários (RF01, D03)."""

    def autenticar(self, matricula: str, senha: str) -> UsuarioAutenticado: ...

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None: ...

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]: ...

    def listar_usuarios(self) -> Sequence[UsuarioAutenticado]: ...

    def criar_usuario(self, dados: CriarUsuarioRequest) -> UsuarioAutenticado: ...

    def redefinir_senha(self, usuario_id: str, nova_senha: str) -> None: ...

    def alterar_propria_senha(
        self, usuario_id: str, senha_atual: str, nova_senha: str
    ) -> None: ...

    def solicitar_recuperacao_senha(self, email: str) -> str | None: ...

    def confirmar_recuperacao_senha(self, token: str, nova_senha: str) -> None: ...


class ILimitadorTentativas(Protocol):
    """Janela deslizante de falhas por chave (conta ou IP) — RNF04 / V02."""

    def verificar(self, chave: str, maximo: int) -> None: ...

    def registrar_falha(self, chave: str) -> None: ...

    def limpar(self, chave: str) -> None: ...


class IListaRevogacao(Protocol):
    """Denylist de `jti` até a expiração natural do token — V09."""

    def revogar(self, jti: str, expira_em: datetime) -> None: ...

    def esta_revogado(self, jti: str) -> bool: ...
