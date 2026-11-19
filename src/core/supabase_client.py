"""Cliente HTTP leve para a Data API (PostgREST) e Auth API do Supabase."""

from typing import Any, cast

import httpx

from src.core.exceptions import ConflitoConcorrencia, ErroDominio, log_app


class ErroPersistenciaSupabase(ErroDominio):
    status_code = 502
    codigo = "ERRO_PERSISTENCIA"


class SupabaseClient:
    """Wrapper fino sobre httpx.Client com chave secret (exclusivo do backend)."""

    def __init__(self, url: str, secret_key: str, timeout: float = 15.0) -> None:
        self._root_url = url.rstrip("/")
        self._base_url = self._root_url + "/rest/v1"
        self._secret_key = secret_key
        self._headers = {
            "apikey": secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def healthcheck(self) -> bool:
        try:
            r = self._http.get("/campi", params={"select": "id", "limit": "1"})
            return r.status_code in (200, 206)
        except httpx.HTTPError:
            return False

    def verificar_senha_auth(self, email: str, senha: str, api_key: str) -> bool:
        """Valida credenciais contra Supabase Auth (GoTrue) em produção (V20)."""
        try:
            r = httpx.post(
                f"{self._root_url}/auth/v1/token",
                params={"grant_type": "password"},
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"email": email, "password": senha},
                timeout=10.0,
            )
            return r.status_code == 200
        except httpx.HTTPError as exc:
            log_app.error("Falha ao contatar Supabase Auth: %s", exc)
            return False

    def _auth_admin_headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

    def criar_usuario_auth(
        self, email: str, senha: str, *, deve_redefinir_senha: bool = False
    ) -> str:
        """Cria usuário no Supabase Auth e retorna o UUID."""
        try:
            r = httpx.post(
                f"{self._root_url}/auth/v1/admin/users",
                headers=self._auth_admin_headers(),
                json={
                    "email": email,
                    "password": senha,
                    "email_confirm": True,
                    "app_metadata": {"deve_redefinir_senha": deve_redefinir_senha},
                },
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            log_app.error("Falha de rede ao criar usuário no Supabase Auth: %s", exc)
            raise ErroPersistenciaSupabase("Serviço de autenticação temporariamente indisponível.") from exc
        if r.status_code in (409, 422):
            raise ConflitoConcorrencia("E-mail já cadastrado no serviço de autenticação.")
        if r.status_code >= 400:
            log_app.error("Erro Supabase Auth criar usuário (%s): %s", r.status_code, r.text[:300])
            raise ErroPersistenciaSupabase("Não foi possível criar o usuário no serviço de autenticação.")
        dados = r.json()
        return str(dados["id"])

    def obter_flag_redefinir_senha_auth(self, usuario_id: str) -> bool:
        """Lê `app_metadata.deve_redefinir_senha` no Supabase Auth (não editável pelo usuário)."""
        try:
            r = httpx.get(
                f"{self._root_url}/auth/v1/admin/users/{usuario_id}",
                headers=self._auth_admin_headers(),
                timeout=10.0,
            )
            if r.status_code != 200:
                return False
            app_meta = r.json().get("app_metadata") or {}
            return bool(app_meta.get("deve_redefinir_senha", False))
        except httpx.HTTPError:
            return False

    def deletar_usuario_auth(self, usuario_id: str) -> None:
        try:
            httpx.delete(
                f"{self._root_url}/auth/v1/admin/users/{usuario_id}",
                headers=self._auth_admin_headers(),
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log_app.error("Falha ao reverter usuário no Supabase Auth: %s", exc)

    def atualizar_senha_auth(
        self, usuario_id: str, nova_senha: str, *, deve_redefinir_senha: bool = False
    ) -> None:
        """Atualiza a senha e a flag `app_metadata.deve_redefinir_senha` no Supabase Auth."""
        try:
            r = httpx.put(
                f"{self._root_url}/auth/v1/admin/users/{usuario_id}",
                headers=self._auth_admin_headers(),
                json={
                    "password": nova_senha,
                    "app_metadata": {"deve_redefinir_senha": deve_redefinir_senha},
                },
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            log_app.error("Falha de rede ao atualizar senha no Supabase Auth: %s", exc)
            raise ErroPersistenciaSupabase("Serviço de autenticação temporariamente indisponível.") from exc
        if r.status_code >= 400:
            log_app.error("Erro Supabase Auth atualizar senha (%s): %s", r.status_code, r.text[:300])
            raise ErroPersistenciaSupabase("Não foi possível atualizar a senha.")

    def solicitar_recuperacao_auth(self, email: str, api_key: str) -> None:
        """Dispara e-mail de recuperação de senha nativo do Supabase Auth."""
        try:
            httpx.post(
                f"{self._root_url}/auth/v1/recover",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"email": email},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            log_app.error("Falha ao solicitar recuperação no Supabase Auth: %s", exc)

    def select(self, tabela: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        r = self._request("GET", f"/{tabela}", params=params)
        dados = r.json()
        if not isinstance(dados, list):
            raise ErroPersistenciaSupabase("Erro ao consultar serviço de persistência.")
        return cast(list[dict[str, Any]], dados)

    def insert(self, tabela: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._request(
            "POST",
            f"/{tabela}",
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        dados = r.json()
        if isinstance(dados, list) and dados:
            return cast(dict[str, Any], dados[0])
        if isinstance(dados, dict):
            return cast(dict[str, Any], dados)
        raise ErroPersistenciaSupabase("Erro ao gravar no serviço de persistência.")

    def update(self, tabela: str, filtros: dict[str, str],
               payload: dict[str, Any]) -> list[dict[str, Any]]:
        r = self._request(
            "PATCH",
            f"/{tabela}",
            params=filtros,
            json=payload,
            headers={"Prefer": "return=representation"},
        )
        dados = r.json()
        if isinstance(dados, list):
            return cast(list[dict[str, Any]], dados)
        return []

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            r = self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            log_app.error("Falha de rede Supabase %s %s: %s", method, path, exc)
            raise ErroPersistenciaSupabase("Serviço de persistência temporariamente indisponível.") from exc
        if r.status_code == 409:
            raise ConflitoConcorrencia("Conflito de integridade/concorrência no banco de dados.")
        if r.status_code >= 400:
            # V22: loga detalhes internamente e devolve mensagem genérica ao cliente.
            log_app.error("Erro Supabase (%s) em %s %s: %s", r.status_code, method, path, r.text[:300])
            raise ErroPersistenciaSupabase("Erro ao comunicar com o serviço de persistência.")
        return r
