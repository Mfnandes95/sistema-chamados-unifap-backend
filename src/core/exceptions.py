"""Hierarquia de exceções de domínio e handlers HTTP padronizados ({erro, mensagem})."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log_seguranca = logging.getLogger("unifap.seguranca")
log_app = logging.getLogger("unifap.app")


class ErroDominio(Exception):
    status_code: int = 400
    codigo: str = "ERRO_DOMINIO"

    def __init__(self, mensagem: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.headers = headers


class RecursoNaoEncontrado(ErroDominio):
    status_code = 404
    codigo = "RECURSO_NAO_ENCONTRADO"


class NaoAutenticado(ErroDominio):
    status_code = 401
    codigo = "NAO_AUTENTICADO"

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem, {"WWW-Authenticate": "Bearer"})


class AcessoNegado(ErroDominio):
    status_code = 403
    codigo = "ACESSO_NEGADO"


class MuitasTentativas(ErroDominio):
    status_code = 429
    codigo = "MUITAS_TENTATIVAS"

    def __init__(self, mensagem: str, retry_after_segundos: int) -> None:
        super().__init__(mensagem, {"Retry-After": str(max(1, retry_after_segundos))})


class TransicaoInvalida(ErroDominio):
    status_code = 409
    codigo = "TRANSICAO_INVALIDA"


class ConflitoConcorrencia(ErroDominio):
    status_code = 409
    codigo = "CONFLITO_CONCORRENCIA"


class RegraNegocioViolada(ErroDominio):
    status_code = 422
    codigo = "REGRA_NEGOCIO_VIOLADA"


class ValidacaoDominio(ErroDominio):
    status_code = 422
    codigo = "VALIDACAO_DOMINIO"


class ArquivoInvalido(ErroDominio):
    status_code = 415
    codigo = "ARQUIVO_INVALIDO"


class ArquivoMuitoGrande(ErroDominio):
    status_code = 413
    codigo = "ARQUIVO_MUITO_GRANDE"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


async def _tratar_erro_dominio(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ErroDominio)
    if isinstance(exc, NaoAutenticado | AcessoNegado | MuitasTentativas):
        log_seguranca.warning("%s %s %s ip=%s: %s", exc.codigo, request.method,
                              request.url.path, _ip(request), exc.mensagem)
    return JSONResponse(status_code=exc.status_code,
                        content={"erro": exc.codigo, "mensagem": exc.mensagem},
                        headers=exc.headers)


async def _tratar_validacao(request: Request, exc: Exception) -> JSONResponse:
    """V14: nunca ecoa `input`/`ctx` (evita refletir senhas e payloads)."""
    assert isinstance(exc, RequestValidationError)
    detalhes: list[dict[str, Any]] = [
        {"campo": [str(p) for p in e.get("loc", ())], "mensagem": e.get("msg", ""),
         "tipo": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=jsonable_encoder(
        {"erro": "VALIDACAO_PAYLOAD", "mensagem": "Requisição inválida.", "detalhes": detalhes}))


async def _tratar_http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return JSONResponse(status_code=exc.status_code,
                        content={"erro": f"HTTP_{exc.status_code}", "mensagem": str(exc.detail)},
                        headers=getattr(exc, "headers", None))


async def _tratar_inesperado(request: Request, exc: Exception) -> JSONResponse:
    log_app.exception("Erro não tratado em %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
                        content={"erro": "ERRO_INTERNO", "mensagem": "Erro interno do servidor."})


def registrar_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ErroDominio, _tratar_erro_dominio)
    app.add_exception_handler(RequestValidationError, _tratar_validacao)
    app.add_exception_handler(StarletteHTTPException, _tratar_http)
    app.add_exception_handler(Exception, _tratar_inesperado)
