"""Bootstrap FastAPI e composition root (único ponto que conhece implementações concretas)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import Settings, obter_settings
from src.core.container import Container
from src.core.exceptions import registrar_handlers
from src.core.frontend import montar_frontend
from src.core.middleware import CabecalhosSegurancaMiddleware
from src.core.supabase_client import SupabaseClient
from src.modules.autenticacao.interfaces import IAutenticadorInstitucional
from src.modules.autenticacao.router import router as auth_router
from src.modules.autenticacao.service import (
    InMemoryAuthAdapter,
    InMemoryLimitadorTentativas,
    InMemoryListaRevogacao,
)
from src.modules.autenticacao.supabase_adapter import SupabaseAuthAdapter
from src.modules.catalogo_locais.interfaces import IValidadorCatalogo
from src.modules.catalogo_locais.router import router as catalogo_router
from src.modules.catalogo_locais.service import InMemoryCatalogoAdapter
from src.modules.catalogo_locais.supabase_adapter import SupabaseCatalogoAdapter
from src.modules.chamados.domain.avaliador_prioridade import AvaliadorDePrioridade
from src.modules.chamados.domain.value_objects import GeradorProtocoloUnifap
from src.modules.chamados.gestor_service import GestorDeChamado
from src.modules.chamados.interfaces import IRepositorioChamado
from src.modules.chamados.repository import InMemoryRepositorioChamado
from src.modules.chamados.router import router as chamados_router
from src.modules.chamados.supabase_repository import SupabaseRepositorioChamado
from src.modules.evidencias.router import router as evidencias_router
from src.modules.evidencias.storage_service import ServicoArmazenamentoEvidencias
from src.modules.notificacoes.adapters import InMemoryPushAdapter, InMemorySmtpAdapter
from src.modules.notificacoes.service import (
    BackgroundNotificationService,
    DiretorioDestinatariosInstitucional,
)
from src.modules.relatorios.router import router as relatorios_router
from src.modules.relatorios.service import ServicoRelatorios
from src.modules.triagem.router import router as triagem_router
from src.modules.triagem.service import ServicoTriagem

_MARGEM_MULTIPART_BYTES = 64 * 1024


def montar_container(
    settings: Settings,
) -> tuple[Container, SupabaseClient | None]:
    supabase_client: SupabaseClient | None = None
    autenticador: IAutenticadorInstitucional
    catalogo: IValidadorCatalogo
    repositorio: IRepositorioChamado

    if settings.usar_supabase:
        assert settings.supabase_url and settings.supabase_secret_key
        supabase_client = SupabaseClient(settings.supabase_url, settings.supabase_secret_key)
        autenticador = SupabaseAuthAdapter(
            supabase_client,
            permitir_senha_demo=settings.permitir_senha_demo,
            publishable_key=settings.supabase_key,
        )
        catalogo = SupabaseCatalogoAdapter(supabase_client)
        repositorio = SupabaseRepositorioChamado(supabase_client)
    else:
        autenticador = InMemoryAuthAdapter()
        catalogo = InMemoryCatalogoAdapter()
        repositorio = InMemoryRepositorioChamado()

    limitador_login = InMemoryLimitadorTentativas(
        janela=timedelta(minutes=settings.login_janela_minutos))
    revogacao = InMemoryListaRevogacao()
    notificacoes = BackgroundNotificationService(
        canais=[InMemorySmtpAdapter(), InMemoryPushAdapter()],
        diretorio=DiretorioDestinatariosInstitucional(autenticador),
    )
    gestor = GestorDeChamado(
        repositorio=repositorio,
        catalogo=catalogo,
        avaliador=AvaliadorDePrioridade(),
        gerador_protocolo=GeradorProtocoloUnifap(),
        publicador=notificacoes,
        prazo_reabertura=timedelta(days=settings.prazo_reabertura_dias),
        max_reaberturas=settings.max_reaberturas,
        max_evidencias=settings.max_evidencias_por_chamado,
    )
    container = Container(
        settings=settings,
        autenticador=autenticador,
        limitador_login=limitador_login,
        revogacao=revogacao,
        catalogo=catalogo,
        gestor_chamados=gestor,
        triagem=ServicoTriagem(gestor, autenticador),
        evidencias=ServicoArmazenamentoEvidencias(
            gestor,
            settings.upload_dir,
            settings.max_upload_bytes,
            supabase_client=supabase_client,
        ),
        notificacoes=notificacoes,
        relatorios=ServicoRelatorios(gestor),
    )
    return container, supabase_client


def criar_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or obter_settings()
    if container is None:
        instancia, supabase_client = montar_container(settings)
    else:
        instancia, supabase_client = container, None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async def _loop_manutencao() -> None:
            while True:
                await asyncio.sleep(settings.intervalo_manutencao_segundos)
                instancia.gestor_chamados.fechar_resolvidos_expirados()
                await instancia.notificacoes.processar_pendentes()

        tarefa = asyncio.create_task(_loop_manutencao())
        try:
            yield
        finally:
            tarefa.cancel()
            with suppress(asyncio.CancelledError):
                await tarefa
            if supabase_client is not None:
                supabase_client.close()

    app = FastAPI(
        title=settings.nome_app,
        version="0.1.0",
        max_body_size=settings.max_corpo_bytes,  # V04: teto global para rotas JSON
        docs_url=None if settings.producao else "/docs",  # V15
        redoc_url=None if settings.producao else "/redoc",
        openapi_url=None if settings.producao else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.container = instancia
    app.state.supabase_client = supabase_client
    app.add_middleware(CabecalhosSegurancaMiddleware, hsts=settings.producao)
    # V16: auth é Bearer JWT (sem cookies), portanto allow_credentials=False.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"],
                       expose_headers=["X-New-Access-Token"])
    registrar_handlers(app)
    for r in (auth_router, catalogo_router, chamados_router, triagem_router, relatorios_router):
        app.include_router(r)
    # V04: teto de corpo e limite de partes no upload antes de gravar spool em disco.
    app.include_router(
        evidencias_router,
        max_body_size=settings.max_upload_bytes + _MARGEM_MULTIPART_BYTES,
        form_limits={"max_files": 1, "max_fields": 0},
    )

    @app.get("/api/v1/info", tags=["infra"])
    def info() -> dict[str, str]:
        dados = {
            "servico": settings.nome_app,
            "versao": "0.1.0",
            "status": "ok",
            "persistencia": "supabase" if supabase_client is not None else "memoria",
            "health": "/health",
        }
        if not settings.producao:
            dados["docs"] = "/docs"
            dados["redoc"] = "/redoc"
        return dados

    @app.get("/health", tags=["infra"])
    def health() -> dict[str, object]:
        if supabase_client is not None:
            conectado = supabase_client.healthcheck()
            if settings.producao:
                return {"status": "ok" if conectado else "degradado"}
            return {
                "status": "ok" if conectado else "degradado",
                "persistencia": "supabase",
                "banco_conectado": conectado,
            }
        if settings.producao:
            return {"status": "ok"}
        return {"status": "ok", "persistencia": "memoria", "banco_conectado": True}

    montar_frontend(app)

    return app


app = criar_app()
