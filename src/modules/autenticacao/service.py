"""Adaptadores em memória do módulo de autenticação.

- InMemoryAuthAdapter: simula a base institucional (SIGAA/LDAP) com usuários seed.
- InMemoryLimitadorTentativas: proteção contra força bruta (V02).
- InMemoryListaRevogacao: logout / revogação de tokens (V09).
"""

import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.core.exceptions import MuitasTentativas, NaoAutenticado
from src.core.security import HASH_ISCA, gerar_hash_senha, verificar_senha
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado

SENHA_PADRAO_SEED = "Unifap@2026"
Relogio = Callable[[], datetime]


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _RegistroUsuario:
    usuario: UsuarioAutenticado
    hash_senha: str


def usuarios_seed() -> list[UsuarioAutenticado]:
    return [
        UsuarioAutenticado(id="u-sol-1", matricula="20230001", nome="Ana Discente",
                           email="ana@unifap.br", perfil=Perfil.SOLICITANTE, vinculo_ativo=True),
        UsuarioAutenticado(id="u-sol-2", matricula="20190002", nome="Bruno Egresso",
                           email="bruno@unifap.br", perfil=Perfil.SOLICITANTE, vinculo_ativo=False),
        UsuarioAutenticado(id="u-sol-3", matricula="20230003", nome="Carla Docente",
                           email="carla@unifap.br", perfil=Perfil.SOLICITANTE, vinculo_ativo=True),
        UsuarioAutenticado(id="u-exe-1", matricula="30000001", nome="Diego Eletricista",
                           email="diego@unifap.br", perfil=Perfil.EXECUTOR, vinculo_ativo=True,
                           setor="ELETRICA"),
        UsuarioAutenticado(id="u-exe-2", matricula="30000002", nome="Elisa TI",
                           email="elisa@unifap.br", perfil=Perfil.EXECUTOR, vinculo_ativo=True,
                           setor="TI"),
        UsuarioAutenticado(id="u-ges-1", matricula="40000001", nome="Fábio Gestor",
                           email="fabio@unifap.br", perfil=Perfil.GESTOR, vinculo_ativo=True,
                           setor="PREFEITURA"),
    ]


class InMemoryAuthAdapter:
    def __init__(self, usuarios: Sequence[UsuarioAutenticado] | None = None,
                 senha_padrao: str = SENHA_PADRAO_SEED) -> None:
        hash_padrao = gerar_hash_senha(senha_padrao)
        self._por_matricula: dict[str, _RegistroUsuario] = {}
        self._por_id: dict[str, UsuarioAutenticado] = {}
        for u in usuarios if usuarios is not None else usuarios_seed():
            self._por_matricula[u.matricula] = _RegistroUsuario(u, hash_padrao)
            self._por_id[u.id] = u

    def autenticar(self, matricula: str, senha: str) -> UsuarioAutenticado:
        registro = self._por_matricula.get(matricula)
        # V08: sempre executa Argon2 (hash isca) para não revelar matrículas pelo tempo.
        valido = verificar_senha(senha, registro.hash_senha if registro else HASH_ISCA)
        if registro is None or not valido:
            raise NaoAutenticado("Matrícula ou senha inválidas.")
        return registro.usuario

    def obter_por_id(self, usuario_id: str) -> UsuarioAutenticado | None:
        return self._por_id.get(usuario_id)

    def listar_por_perfil(self, perfil: Perfil) -> Sequence[UsuarioAutenticado]:
        return tuple(u for u in self._por_id.values() if u.perfil is perfil)


class InMemoryLimitadorTentativas:
    """Janela deslizante thread-safe. Substituível por Redis mantendo o Protocol."""

    _LIMITE_CHAVES = 100_000

    def __init__(self, janela: timedelta, relogio: Relogio = _agora) -> None:
        self._janela = janela
        self._relogio = relogio
        self._falhas: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()

    def _expurgar(self, chave: str, agora: datetime) -> deque[datetime] | None:
        falhas = self._falhas.get(chave)
        if falhas is None:
            return None
        while falhas and agora - falhas[0] >= self._janela:
            falhas.popleft()
        if not falhas:
            del self._falhas[chave]
            return None
        return falhas

    def verificar(self, chave: str, maximo: int) -> None:
        agora = self._relogio()
        with self._lock:
            falhas = self._expurgar(chave, agora)
            if falhas is not None and len(falhas) >= maximo:
                restante = falhas[0] + self._janela - agora
                raise MuitasTentativas("Muitas tentativas de login. Tente novamente mais tarde.",
                                       int(restante.total_seconds()) + 1)

    def registrar_falha(self, chave: str) -> None:
        agora = self._relogio()
        with self._lock:
            if len(self._falhas) >= self._LIMITE_CHAVES:  # evita crescimento ilimitado
                for k in list(self._falhas):
                    self._expurgar(k, agora)
            self._falhas.setdefault(chave, deque()).append(agora)

    def limpar(self, chave: str) -> None:
        with self._lock:
            self._falhas.pop(chave, None)


class InMemoryListaRevogacao:
    def __init__(self, relogio: Relogio = _agora) -> None:
        self._relogio = relogio
        self._revogados: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def revogar(self, jti: str, expira_em: datetime) -> None:
        agora = self._relogio()
        with self._lock:
            for k in [k for k, exp in self._revogados.items() if exp <= agora]:
                del self._revogados[k]
            self._revogados[jti] = expira_em

    def esta_revogado(self, jti: str) -> bool:
        with self._lock:
            return jti in self._revogados
