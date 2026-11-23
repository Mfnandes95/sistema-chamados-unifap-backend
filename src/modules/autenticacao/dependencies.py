"""Guards RBAC (RN02, RNF04)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.container import ContainerDep
from src.core.exceptions import AcessoNegado, NaoAutenticado
from src.core.security import decodificar_token
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Sessao:
    usuario: UsuarioAutenticado
    jti: str
    expira_em: datetime


def obter_sessao(
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    container: ContainerDep,
) -> Sessao:
    if credenciais is None:
        raise NaoAutenticado("Credenciais ausentes.")
    claims = decodificar_token(credenciais.credentials, container.settings)
    if container.revogacao.esta_revogado(claims.jti):
        raise NaoAutenticado("Sessão encerrada.")
    # Usuário é sempre recarregado: perfil/vínculo vêm da fonte institucional, não do token.
    usuario = container.autenticador.obter_por_id(claims.sub)
    if usuario is None:
        raise NaoAutenticado("Usuário não encontrado.")
    return Sessao(usuario, claims.jti, claims.expira_em)


SessaoAtual = Annotated[Sessao, Depends(obter_sessao)]


def obter_usuario_para_troca(sessao: SessaoAtual) -> UsuarioAutenticado:
    """Permite consultar /auth/me e trocar a senha mesmo com deve_redefinir_senha=True."""
    return sessao.usuario


UsuarioParaTroca = Annotated[UsuarioAutenticado, Depends(obter_usuario_para_troca)]


def obter_usuario_atual(sessao: SessaoAtual) -> UsuarioAutenticado:
    if sessao.usuario.deve_redefinir_senha:
        raise AcessoNegado("É obrigatório redefinir sua senha antes de continuar.")
    return sessao.usuario


UsuarioAtual = Annotated[UsuarioAutenticado, Depends(obter_usuario_atual)]
"""Somente leitura: usuários com vínculo inativo ainda consultam seus próprios chamados,
mas usuários com redefinição de senha pendente ficam bloqueados até concluírem a troca."""


def _exigir(
    *perfis: Perfil, permitir_troca_pendente: bool = False
) -> Callable[[UsuarioAutenticado], UsuarioAutenticado]:
    if permitir_troca_pendente:
        def guard_troca(usuario: UsuarioParaTroca) -> UsuarioAutenticado:
            if usuario.perfil not in perfis:
                raise AcessoNegado("Perfil sem permissão para esta operação.")
            if not usuario.vinculo_ativo:
                raise AcessoNegado("RN02: vínculo institucional inativo.")
            return usuario

        return guard_troca

    def guard(usuario: UsuarioAtual) -> UsuarioAutenticado:
        if usuario.perfil not in perfis:
            raise AcessoNegado("Perfil sem permissão para esta operação.")
        if not usuario.vinculo_ativo:
            raise AcessoNegado("RN02: vínculo institucional inativo.")
        return usuario

    return guard


exigir_usuario_ativo = _exigir(*Perfil)
exigir_usuario_ativo_para_troca = _exigir(*Perfil, permitir_troca_pendente=True)
exigir_solicitante_ativo = _exigir(Perfil.SOLICITANTE)
exigir_executor = _exigir(Perfil.EXECUTOR)
exigir_gestor = _exigir(Perfil.GESTOR)
exigir_admin = _exigir(Perfil.ADMIN)
exigir_gestor_ou_admin = _exigir(Perfil.GESTOR, Perfil.ADMIN)
exigir_equipe_tecnica = _exigir(Perfil.EXECUTOR, Perfil.GESTOR, Perfil.ADMIN)

UsuarioAtivo = Annotated[UsuarioAutenticado, Depends(exigir_usuario_ativo)]
"""Obrigatório em toda operação de escrita (RN02 / V03)."""
UsuarioAtivoParaTroca = Annotated[UsuarioAutenticado, Depends(exigir_usuario_ativo_para_troca)]
"""Permite apenas a troca obrigatória de senha quando deve_redefinir_senha=True."""
SolicitanteAtivo = Annotated[UsuarioAutenticado, Depends(exigir_solicitante_ativo)]
Executor = Annotated[UsuarioAutenticado, Depends(exigir_executor)]
Gestor = Annotated[UsuarioAutenticado, Depends(exigir_gestor)]
Admin = Annotated[UsuarioAutenticado, Depends(exigir_admin)]
GestorOuAdmin = Annotated[UsuarioAutenticado, Depends(exigir_gestor_ou_admin)]
EquipeTecnica = Annotated[UsuarioAutenticado, Depends(exigir_equipe_tecnica)]
