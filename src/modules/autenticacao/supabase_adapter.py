"""Adaptador Supabase para IAutenticadorInstitucional (lê a tabela `perfis`)."""

from collections.abc import Sequence
from typing import Any

from src.core.exceptions import NaoAutenticado
from src.core.security import HASH_ISCA, gerar_hash_senha, verificar_senha
from src.core.supabase_client import SupabaseClient
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.autenticacao.service import SENHA_PADRAO_SEED


def _escolher_perfil(papeis: Sequence[str]) -> Perfil:
    baixos = {p.lower() for p in papeis}
    if "gestor" in baixos or "admin" in baixos or "reitoria" in baixos:
        return Perfil.GESTOR
    if "executor" in baixos:
        return Perfil.EXECUTOR
    return Perfil.SOLICITANTE


def _para_usuario(row: dict[str, Any]) -> UsuarioAutenticado:
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
    )


class SupabaseAuthAdapter:
    """Cumpre IAutenticadorInstitucional consultando `public.perfis` no Supabase."""

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

    def autenticar(self, matricula: str, senha: str) -> UsuarioAutenticado:
        linhas = self._client.select(
            "perfis",
            {"select": "*", "matricula_siape": f"eq.{matricula}", "limit": "1"},
        )
        encontrado = linhas[0] if linhas else None
        if self._permitir_senha_demo:
            # V08: mantém custo Argon2 constante mesmo se a matrícula não existir.
            valido = verificar_senha(senha, self._hash_padrao if encontrado else HASH_ISCA)
        else:
            # V20: em produção, valida contra Supabase Auth real (nunca aceita senha demo).
            if encontrado is None or not self._publishable_key:
                verificar_senha(senha, HASH_ISCA)
                valido = False
            else:
                valido = self._client.verificar_senha_auth(
                    str(encontrado["email"]), senha, self._publishable_key
                )
        if encontrado is None or not valido:
            raise NaoAutenticado("Matrícula ou senha inválidas.")
        return _para_usuario(encontrado)

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None:
        linhas = self._client.select(
            "perfis", {"select": "*", "id": f"eq.{usuario_id}", "limit": "1"}
        )
        return _para_usuario(linhas[0]) if linhas else None

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]:
        linhas = self._client.select("perfis", {"select": "*"})
        return tuple(u for row in linhas if (u := _para_usuario(row)).perfil is perfil)
