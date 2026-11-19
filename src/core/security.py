"""Hashing Argon2 (pwdlib) e emissão/decodificação de JWT (PyJWT)."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from src.core.config import Settings
from src.core.exceptions import NaoAutenticado

_hasher = PasswordHash((Argon2Hasher(),))
_EMISSOR = "unifap-chamados"


def gerar_hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def verificar_senha(senha: str, hash_senha: str) -> bool:
    try:
        return _hasher.verify(senha, hash_senha)
    except Exception:
        return False


# V08: hash "isca" usado quando a matrícula não existe, igualando o custo da resposta.
HASH_ISCA = gerar_hash_senha(secrets.token_urlsafe(32))


@dataclass(frozen=True, slots=True)
class ClaimsToken:
    sub: str
    perfil: str
    jti: str
    expira_em: datetime


def criar_token(sub: str, perfil: str, settings: Settings) -> str:
    agora = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "perfil": perfil,
        "iat": agora,
        "nbf": agora,
        "exp": agora + timedelta(minutes=settings.jwt_expire_minutes),
        "iss": _EMISSOR,
        "aud": settings.jwt_audience,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decodificar_token(token: str, settings: Settings) -> ClaimsToken:
    try:
        dados: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # lista fixa: impede 'none'/confusão de alg
            issuer=_EMISSOR,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise NaoAutenticado("Token expirado.") from exc
    except jwt.PyJWTError as exc:
        raise NaoAutenticado("Token inválido.") from exc
    sub, perfil, jti, exp = dados["sub"], dados.get("perfil"), dados["jti"], dados["exp"]
    if not (isinstance(sub, str) and isinstance(perfil, str) and isinstance(jti, str)
            and isinstance(exp, int)):
        raise NaoAutenticado("Token inválido.")
    return ClaimsToken(sub, perfil, jti, datetime.fromtimestamp(exp, UTC))
