"""Adaptador Supabase para IAutenticadorInstitucional (Supabase Auth + `public.perfis`)."""

import secrets
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.exceptions import (
    ConflitoConcorrencia,
    NaoAutenticado,
    RecursoNaoEncontrado,
    ValidacaoDominio,
)
from src.core.security import HASH_ISCA, gerar_hash_senha, validar_forca_senha, verificar_senha
from src.core.supabase_client import SupabaseClient
from src.modules.autenticacao.schemas import CriarUsuarioRequest, Perfil, UsuarioAutenticado
from src.modules.autenticacao.service import SENHA_PADRAO_SEED

_PERFIL_PARA_PAPEIS_DB: dict[Perfil, list[str]] = {
    Perfil.ADMIN: ["admin", "gestor", "solicitante"],
    Perfil.GESTOR: ["gestor", "solicitante"],
    Perfil.EXECUTOR: ["executor", "solicitante"],
    Perfil.SOLICITANTE: ["solicitante"],
}


@dataclass(frozen=True, slots=True)
class _TokenRecuperacao:
    usuario_id: str
    expira_em: datetime


def _escolher_perfil(papeis: Sequence[str]) -> Perfil:
    baixos = {p.lower() for p in papeis}
    if "admin" in baixos:
        return Perfil.ADMIN
    if "gestor" in baixos or "reitoria" in baixos:
        return Perfil.GESTOR
    if "executor" in baixos:
        return Perfil.EXECUTOR
    return Perfil.SOLICITANTE


def _para_usuario(row: dict[str, Any], *, deve_redefinir_senha: bool = False) -> UsuarioAutenticado:
    papeis = row.get("perfis") or ["solicitante"]
    ativo = bool(row.get("vinculo_ativo", False)) and bool(row.get("acesso_local_ativo", True))
    return UsuarioAutenticado(
        id=str(row["id"]),
        matricula=str(row["matricula_siape"]),
        nome=str(row["nome"]),
        email=str(row["email"]),
        perfil=_escolher_perfil([str(p) for p in papeis]),
        vinculo_ativo=ativo,
        setor=str(row["setor_id"]) if row.get("setor_id") else None,
        deve_redefinir_senha=deve_redefinir_senha,
    )


class SupabaseAuthAdapter:
    """Cumpre IAutenticadorInstitucional via Supabase Auth + `public.perfis`."""

    def __init__(
        self,
        client: SupabaseClient,
        *,
        permitir_senha_demo: bool = True,
        publishable_key: str | None = None,
        senha_padrao: str = SENHA_PADRAO_SEED,
    ) -> None:
        self._client = client
        self._permitir_senha_demo = permitir_senha_demo
        self._publishable_key = publishable_key
        self._hash_padrao = gerar_hash_senha(senha_padrao)
        self._lock = threading.RLock()
        self._tokens_recuperacao: dict[str, _TokenRecuperacao] = {}

    def _validar_credenciais(self, row: dict[str, Any], senha: str) -> bool:
        # Primeiro valida contra a senha real no Supabase Auth (se publishable_key disponível).
        if self._publishable_key and self._client.verificar_senha_auth(
            str(row["email"]), senha, self._publishable_key
        ):
            return True
        if self._permitir_senha_demo:
            return verificar_senha(senha, self._hash_padrao)
        return False

    def autenticar(self, matricula: str, senha: str) -> UsuarioAutenticado:
        linhas = self._client.select(
            "perfis",
            {"select": "*", "matricula_siape": f"eq.{matricula}", "limit": "1"},
        )
        encontrado = linhas[0] if linhas else None
        if encontrado is None:
            verificar_senha(senha, HASH_ISCA)  # V08
            raise NaoAutenticado("Matrícula ou senha inválidas.")
        if not self._validar_credenciais(encontrado, senha):
            raise NaoAutenticado("Matrícula ou senha inválidas.")
        deve_trocar = self._client.obter_flag_redefinir_senha_auth(str(encontrado["id"]))
        return _para_usuario(encontrado, deve_redefinir_senha=deve_trocar)

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None:
        linhas = self._client.select(
            "perfis", {"select": "*", "id": f"eq.{usuario_id}", "limit": "1"}
        )
        if not linhas:
            return None
        deve_trocar = self._client.obter_flag_redefinir_senha_auth(usuario_id)
        return _para_usuario(linhas[0], deve_redefinir_senha=deve_trocar)

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]:
        linhas = self._client.select("perfis", {"select": "*"})
        return tuple(u for row in linhas if (u := _para_usuario(row)).perfil is perfil)

    def listar_usuarios(self) -> Sequence[UsuarioAutenticado]:
        linhas = self._client.select("perfis", {"select": "*", "order": "nome.asc"})
        return tuple(_para_usuario(row) for row in linhas)

    def criar_usuario(self, dados: CriarUsuarioRequest) -> UsuarioAutenticado:
        existentes = self._client.select(
            "perfis",
            {"select": "id", "matricula_siape": f"eq.{dados.matricula}", "limit": "1"},
        )
        if existentes:
            raise ConflitoConcorrencia("Matrícula já cadastrada.")

        usuario_id = self._client.criar_usuario_auth(
            dados.email.lower(), dados.senha, deve_redefinir_senha=dados.deve_redefinir_senha
        )
        try:
            inserido = self._client.insert("perfis", {
                "id": usuario_id,
                "nome": dados.nome,
                "email": dados.email.lower(),
                "matricula_siape": dados.matricula,
                "vinculo": dados.vinculo,
                "vinculo_ativo": dados.vinculo_ativo,
                "acesso_local_ativo": True,
                "perfis": _PERFIL_PARA_PAPEIS_DB[dados.perfil],
                "setor_id": dados.setor,
            })
        except BaseException:
            self._client.deletar_usuario_auth(usuario_id)
            raise
        return _para_usuario(inserido, deve_redefinir_senha=dados.deve_redefinir_senha)

    def redefinir_senha(
        self, usuario_id: str, nova_senha: str, *, deve_redefinir_senha: bool = False
    ) -> None:
        if self.obter_por_id(usuario_id) is None:
            raise RecursoNaoEncontrado("Usuário não encontrado.")
        self._client.atualizar_senha_auth(
            usuario_id, nova_senha, deve_redefinir_senha=deve_redefinir_senha
        )

    def alterar_propria_senha(
        self, usuario_id: str, senha_atual: str, nova_senha: str
    ) -> None:
        if senha_atual == nova_senha:
            raise ValidacaoDominio("A nova senha deve ser diferente da senha atual.")
        linhas = self._client.select(
            "perfis", {"select": "*", "id": f"eq.{usuario_id}", "limit": "1"}
        )
        if not linhas or not self._validar_credenciais(linhas[0], senha_atual):
            raise NaoAutenticado("Senha atual incorreta.")
        validar_forca_senha(
            nova_senha,
            matricula=str(linhas[0]["matricula_siape"]),
            nome=str(linhas[0]["nome"]),
        )
        self._client.atualizar_senha_auth(usuario_id, nova_senha, deve_redefinir_senha=False)

    def solicitar_recuperacao_senha(self, email: str) -> str | None:
        email_norm = email.lower()
        linhas = self._client.select(
            "perfis", {"select": "*", "email": f"eq.{email_norm}", "limit": "1"}
        )
        if not linhas:
            return None
        usuario = _para_usuario(linhas[0])
        if not usuario.vinculo_ativo:
            return None
        if self._publishable_key:
            self._client.solicitar_recuperacao_auth(email_norm, self._publishable_key)
        agora = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens_recuperacao[token] = _TokenRecuperacao(
                usuario.id, agora + timedelta(minutes=15)
            )
        return token

    def confirmar_recuperacao_senha(self, token: str, nova_senha: str) -> None:
        agora = datetime.now(UTC)
        with self._lock:
            reg = self._tokens_recuperacao.pop(token, None)
        if reg is None or reg.expira_em <= agora:
            raise ValidacaoDominio("Token de redefinição inválido ou expirado.")
        alvo = self.obter_por_id(reg.usuario_id)
        if alvo is not None:
            validar_forca_senha(nova_senha, matricula=alvo.matricula, nome=alvo.nome)
        self.redefinir_senha(reg.usuario_id, nova_senha)
