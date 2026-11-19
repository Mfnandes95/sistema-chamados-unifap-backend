"""Middlewares ASGI puros de hardening HTTP (V15)."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PREFIXOS_DOCS = ("/docs", "/redoc", "/openapi.json")
_PREFIXOS_FRONTEND = ("/css/", "/js/", "/assets/", "/bridge.js")
_CSP_API = "default-src 'none'; frame-ancestors 'none'"
_CSP_FRONTEND = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


class CabecalhosSegurancaMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        caminho = str(scope.get("path", ""))
        eh_docs = caminho.startswith(_PREFIXOS_DOCS)
        eh_frontend = caminho in ("/", "/index.html") or caminho.startswith(_PREFIXOS_FRONTEND)

        async def enviar(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h.setdefault("X-Content-Type-Options", "nosniff")
                h.setdefault("X-Frame-Options", "DENY")
                h.setdefault("Referrer-Policy", "no-referrer")
                h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                if eh_frontend:
                    h.setdefault("Content-Security-Policy", _CSP_FRONTEND)
                elif not eh_docs:  # Swagger UI carrega assets de CDN
                    h.setdefault("Content-Security-Policy", _CSP_API)
                    h.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    h.setdefault("Strict-Transport-Security",
                                 "max-age=31536000; includeSubDomains")
            await send(message)

        await self.app(scope, receive, enviar)
