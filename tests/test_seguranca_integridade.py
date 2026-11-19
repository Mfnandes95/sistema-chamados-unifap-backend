"""Suíte dedicada de testes de integridade, segurança (V01-V19) e defeitos funcionais (F01-F04)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.core.config import SEGREDO_DESENVOLVIMENTO, Settings
from src.core.container import Container
from src.core.exceptions import AcessoNegado, ConflitoConcorrencia
from src.main import criar_app, montar_container
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.autenticacao.service import SENHA_PADRAO_SEED, InMemoryAuthAdapter
from src.modules.catalogo_locais.service import InMemoryCatalogoAdapter
from src.modules.chamados.domain.avaliador_prioridade import AvaliadorDePrioridade
from src.modules.chamados.domain.entities import StatusChamado
from src.modules.chamados.domain.value_objects import GeradorProtocoloUnifap, Protocolo
from src.modules.chamados.gestor_service import GestorDeChamado
from src.modules.chamados.interfaces import FiltroChamados
from src.modules.chamados.repository import InMemoryRepositorioChamado
from src.modules.chamados.schemas import AbrirChamadoRequest
from src.modules.evidencias.storage_service import (
    ServicoArmazenamentoEvidencias,
    sanitizar_nome_arquivo,
)
from src.modules.notificacoes.service import (
    BackgroundNotificationService,
    DiretorioDestinatariosInstitucional,
)
from src.modules.relatorios.exporters import exportar_csv, exportar_pdf
from src.modules.relatorios.interfaces import AgregadoDTO, RelatorioHistoricoDTO
from tests.conftest import CHAMADO_VALIDO

H = dict[str, dict[str, str]]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ---------------------------------------------------------------------- V01 / V15 / V16 / V20 / V21 / V23
def test_v01_v16_v20_v23_producao_hardening_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(ambiente="producao", jwt_secret=SEGREDO_DESENVOLVIMENTO, permitir_senha_demo=False)
    with pytest.raises(ValidationError):
        Settings(ambiente="producao", jwt_secret="a" * 40, cors_origins=["*"], permitir_senha_demo=False)
    # V20: proíbe senha demo em produção
    with pytest.raises(ValidationError):
        Settings(ambiente="producao", jwt_secret="a" * 40, cors_origins=["https://unifap.br"],
                 permitir_senha_demo=True)
    # V23: exige HTTPS no Supabase em produção
    with pytest.raises(ValidationError):
        Settings(ambiente="producao", jwt_secret="a" * 40, cors_origins=["https://unifap.br"],
                 permitir_senha_demo=False, supabase_url="http://inseguro.local",
                 supabase_secret_key="sb_secret_test")
    ok = Settings(ambiente="producao", jwt_secret="a" * 40, cors_origins=["https://unifap.br"],
                  permitir_senha_demo=False, supabase_url=None, supabase_secret_key=None)
    assert ok.producao is True


async def test_v15_v21_cabecalhos_seguranca_docs_e_bridge_desabilitados_em_producao(tmp_path: Path) -> None:
    s = Settings(ambiente="producao", jwt_secret="x" * 40,
                 cors_origins=["https://unifap.br"], upload_dir=tmp_path / "u",
                 permitir_senha_demo=False, supabase_url=None, supabase_secret_key=None)
    app_prod = criar_app(s)
    async with AsyncClient(transport=ASGITransport(app=app_prod), base_url="http://test") as c:
        r = await c.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}  # V24: não expõe detalhes internos em produção
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"
        assert "strict-transport-security" in r.headers
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/openapi.json")).status_code == 404
        r_info = await c.get("/api/v1/info")
        assert r_info.status_code == 200 and "docs" not in r_info.json()
        # V21: em produção, frontend não injeta /bridge.js com senha demo
        r_front = await c.get("/")
        assert r_front.status_code == 200 and "/bridge.js" not in r_front.text
        assert (await c.get("/bridge.js")).status_code == 404
        assert (await c.get("/js/app.js")).status_code == 200


# ---------------------------------------------------------------------- V02 / V14
async def test_v02_rate_limit_login_e_v14_nao_ecoa_senha(tmp_path: Path) -> None:
    s = Settings(upload_dir=tmp_path / "u", login_max_tentativas_conta=3,
                 login_max_tentativas_ip=10, supabase_url=None, supabase_secret_key=None)
    app_rl = criar_app(s)
    async with AsyncClient(transport=ASGITransport(app=app_rl), base_url="http://test") as c:
        # V14: senha curta dispara 422 mas NÃO é refletida na resposta
        r_val = await c.post("/api/v1/auth/login",
                             json={"matricula": "20230001", "senha": "segredo"})
        assert r_val.status_code == 422
        assert "segredo" not in r_val.text
        assert r_val.json()["erro"] == "VALIDACAO_PAYLOAD"

        # V02: 3 falhas bloqueiam a 4ª tentativa com 429 + Retry-After
        for _ in range(3):
            r = await c.post("/api/v1/auth/login",
                             json={"matricula": "20230001", "senha": "Errada@2026"})
            assert r.status_code == 401
        r_bloq = await c.post("/api/v1/auth/login",
                              json={"matricula": "20230001", "senha": SENHA_PADRAO_SEED})
        assert r_bloq.status_code == 429
        assert "retry-after" in r_bloq.headers


# ---------------------------------------------------------------------- V09
async def test_v09_logout_revoga_token_e_rejeita_alg_invalido(client: AsyncClient,
                                                              tokens: H,
                                                              settings: Settings) -> None:
    hdr = tokens["solicitante"]
    assert (await client.get("/api/v1/auth/me", headers=hdr)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=hdr)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=hdr)).status_code == 401

    # Token sem audience correta é rejeitado
    forjado = jwt.encode(
        {"sub": "u-ges-1", "perfil": "GESTOR", "iss": "unifap-chamados", "aud": "outro",
         "jti": "123", "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret, algorithm="HS256",
    )
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forjado}"})
    assert r.status_code == 401


# ---------------------------------------------------------------------- V03 / F04
async def test_v03_vinculo_inativo_bloqueado_em_todas_escritas(client: AsyncClient,
                                                               tokens: H) -> None:
    r = await client.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=tokens["solicitante"])
    protocolo = r.json()["protocolo"]
    inativo = tokens["inativo"]
    assert (await client.post(f"/api/v1/chamados/{protocolo}/comentarios",
                              json={"texto": "oi"}, headers=inativo)).status_code == 403
    assert (await client.post(f"/api/v1/chamados/{protocolo}/evidencias",
                              files={"arquivo": ("a.png", PNG, "image/png")},
                              headers=inativo)).status_code == 403
    assert (await client.post(f"/api/v1/chamados/{protocolo}/cancelar",
                              json={"motivo": "Motivo qualquer valido"},
                              headers=inativo)).status_code == 403


def test_f04_abertura_bloqueia_nao_solicitante_no_dominio() -> None:
    auth = InMemoryAuthAdapter()
    gestor = GestorDeChamado(
        InMemoryRepositorioChamado(), InMemoryCatalogoAdapter(), AvaliadorDePrioridade(),
        GeradorProtocoloUnifap(),
        BackgroundNotificationService([], DiretorioDestinatariosInstitucional(auth)),
    )
    usuario_gestor = auth.obter_por_id("u-ges-1")
    assert usuario_gestor is not None
    with pytest.raises(AcessoNegado):
        gestor.abrir_chamado(AbrirChamadoRequest.model_validate(CHAMADO_VALIDO), usuario_gestor)


# ---------------------------------------------------------------------- V04
async def test_v04_teto_corpo_json_e_multipart(tmp_path: Path) -> None:
    s = Settings(upload_dir=tmp_path / "u", max_corpo_bytes=2048, max_upload_bytes=1024,
                 supabase_url=None, supabase_secret_key=None)
    app_lim = criar_app(s)
    async with AsyncClient(transport=ASGITransport(app=app_lim), base_url="http://test") as c:
        r_big = await c.post("/api/v1/auth/login", content=b"{" + b" " * 4096 + b"}",
                             headers={"Content-Type": "application/json"})
        assert r_big.status_code == 413


# ---------------------------------------------------------------------- V05 / V06
def test_v05_v06_concorrencia_otimista_e_duplicidade_protocolo() -> None:
    repo = InMemoryRepositorioChamado()
    auth = InMemoryAuthAdapter()
    sol = auth.obter_por_id("u-sol-1")
    assert sol is not None

    class _GeradorFixo:
        def gerar(self) -> Protocolo:
            return Protocolo("UNIFAP-202611-000001")

    gestor = GestorDeChamado(
        repo, InMemoryCatalogoAdapter(), AvaliadorDePrioridade(), _GeradorFixo(),
        BackgroundNotificationService([], DiretorioDestinatariosInstitucional(auth)),
    )
    chamado = gestor.abrir_chamado(AbrirChamadoRequest.model_validate(CHAMADO_VALIDO), sol)
    # V06: protocolo repetido não sobrescreve
    with pytest.raises(ConflitoConcorrencia):
        gestor.abrir_chamado(AbrirChamadoRequest.model_validate(CHAMADO_VALIDO), sol)

    # V05: dois leitores carregam versão 1; segundo update falha com ConflitoConcorrencia
    c1 = repo.obter(chamado.protocolo)
    c2 = repo.obter(chamado.protocolo)
    assert c1 is not None and c2 is not None
    c1.versao = 2
    repo.salvar(c1, versao_esperada=1)
    c2.versao = 2
    with pytest.raises(ConflitoConcorrencia):
        repo.salvar(c2, versao_esperada=1)


# ---------------------------------------------------------------------- V07 / V11
async def test_v07_anti_enumeracao_e_v11_observacao_interna_oculta(client: AsyncClient,
                                                                   tokens: H) -> None:
    r = await client.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=tokens["solicitante"])
    protocolo = r.json()["protocolo"]

    # V07: outro solicitante recebe 404 (não 403) em ações de escrita
    for rota, payload in (
        ("comentarios", {"texto": "tentativa"}),
        ("cancelar", {"motivo": "Motivo longo suficiente"}),
        ("avaliacao", {"nota": 1}),
    ):
        resp = await client.post(f"/api/v1/chamados/{protocolo}/{rota}",
                                 json=payload, headers=tokens["solicitante2"])
        assert resp.status_code == 404, (rota, resp.status_code)

    # V11: observação do gestor na atribuição não aparece no histórico do solicitante
    await client.post(f"/api/v1/triagem/{protocolo}/atribuir",
                      json={"executor_id": "u-exe-1", "observacao": "NOTA_SECRETA_GESTOR"},
                      headers=tokens["gestor"])
    hist_sol = (await client.get(f"/api/v1/chamados/{protocolo}/historico",
                                 headers=tokens["solicitante"])).text
    hist_ges = (await client.get(f"/api/v1/chamados/{protocolo}/historico",
                                 headers=tokens["gestor"])).text
    assert "NOTA_SECRETA_GESTOR" not in hist_sol
    assert "NOTA_SECRETA_GESTOR" in hist_ges


# ---------------------------------------------------------------------- V10 / V12 / V19
async def test_v10_relatorio_com_data_naive_nao_gera_500(client: AsyncClient, tokens: H) -> None:
    await client.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=tokens["solicitante"])
    r = await client.get(
        "/api/v1/relatorios/historico?data_inicio=2020-01-01T00:00:00&data_fim=2030-01-01T00:00:00",
        headers=tokens["gestor"],
    )
    assert r.status_code == 200
    assert r.json()["total_chamados"] == 1


def test_v12_csv_formula_injection_e_v19_pdf_escape() -> None:
    rel = RelatorioHistoricoDTO(
        gerado_em=datetime(2026, 11, 19, tzinfo=UTC),
        total_chamados=1,
        por_status={"ABERTO": 1},
        por_prioridade={"ALTA": 1},
        por_local=[AgregadoDTO(chave="=cmd|' /C calc'!A0", total=1, resolvidos=0,
                               reaberturas=0, tmr_horas=None)],
        por_equipamento=[AgregadoDTO(chave="TI/PROJETOR\n) Tj ET (INJ", total=1, resolvidos=0,
                                     reaberturas=0, tmr_horas=None)],
        tmr_geral_horas=None,
        media_avaliacao=None,
    )
    csv_txt = exportar_csv(rel).decode("utf-8")
    assert ";'=cmd|" in csv_txt  # fórmula neutralizada com apóstrofo

    pdf_bytes = exportar_pdf(rel)
    assert pdf_bytes.startswith(b"%PDF-1.4\n")
    assert b"\n) Tj ET" not in pdf_bytes


# ---------------------------------------------------------------------- V13 / F03
async def test_v13_paginacao_limite_evidencias_e_f03_fila_oculta_encerrados(tmp_path: Path) -> None:
    s = Settings(upload_dir=tmp_path / "u", max_evidencias_por_chamado=2,
                 supabase_url=None, supabase_secret_key=None)
    c_inst: Container
    c_inst, _ = montar_container(s)
    app_p = criar_app(s, c_inst)
    async with AsyncClient(transport=ASGITransport(app=app_p), base_url="http://test") as c:
        r_sol = await c.post("/api/v1/auth/login",
                             json={"matricula": "20230001", "senha": SENHA_PADRAO_SEED})
        r_ges = await c.post("/api/v1/auth/login",
                             json={"matricula": "40000001", "senha": SENHA_PADRAO_SEED})
        h_sol = {"Authorization": f"Bearer {r_sol.json()['access_token']}"}
        h_ges = {"Authorization": f"Bearer {r_ges.json()['access_token']}"}

        protocolos = []
        for _ in range(3):
            r = await c.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=h_sol)
            protocolos.append(r.json()["protocolo"])

        # Paginação
        pag = await c.get("/api/v1/chamados?limite=2&deslocamento=1", headers=h_sol)
        assert len(pag.json()) == 2

        # Limite de evidências por chamado (máx 2)
        p0 = protocolos[0]
        for i in range(2):
            r = await c.post(f"/api/v1/chamados/{p0}/evidencias",
                             files={"arquivo": (f"f{i}.png", PNG, "image/png")}, headers=h_sol)
            assert r.status_code == 201
        r_excesso = await c.post(f"/api/v1/chamados/{p0}/evidencias",
                                 files={"arquivo": ("f3.png", PNG, "image/png")}, headers=h_sol)
        assert r_excesso.status_code == 422

        # F03: chamado cancelado sai da fila padrão, mas aparece com ?status=CANCELADO
        await c.post(f"/api/v1/chamados/{p0}/cancelar",
                     json={"motivo": "Aberto em duplicidade."}, headers=h_sol)
        fila_padrao = [x["protocolo"] for x in (await c.get("/api/v1/triagem/fila",
                                                            headers=h_ges)).json()]
        assert p0 not in fila_padrao and len(fila_padrao) == 2
        fila_canc = [x["protocolo"] for x in (await c.get("/api/v1/triagem/fila?status=CANCELADO",
                                                          headers=h_ges)).json()]
        assert fila_canc == [p0]


# ---------------------------------------------------------------------- V17
async def test_v17_sanitizacao_nome_e_limpeza_em_falha_de_registro(tmp_path: Path) -> None:
    assert sanitizar_nome_arquivo("../../a\u202egnp.png\x00") == "agnp.png"

    class _RegistroFalho:
        def verificar_pode_anexar(self, protocolo: str, ator: UsuarioAutenticado) -> None:
            return None

        def registrar_evidencia(self, protocolo: str, evidencia: object,
                                ator: UsuarioAutenticado) -> None:
            raise ConflitoConcorrencia("simulado")

    svc = ServicoArmazenamentoEvidencias(_RegistroFalho(), tmp_path, 1024)
    ator = UsuarioAutenticado(id="u1", matricula="20230001", nome="A", email="a@unifap.br",
                              perfil=Perfil.SOLICITANTE, vinculo_ativo=True)
    chunks = iter([PNG, b""])

    async def leitor(_n: int) -> bytes:
        return next(chunks)

    with pytest.raises(ConflitoConcorrencia):
        await svc.anexar("UNIFAP-202611-000001", "foto.png", "image/png", leitor, ator)
    # Nenhum arquivo órfão deixado em disco
    assert list((tmp_path / "UNIFAP-202611-000001").glob("*")) == []


# ---------------------------------------------------------------------- F02
def test_f02_fechamento_automatico_apos_prazo() -> None:
    relogio_atual = [datetime(2026, 11, 1, 10, 0, tzinfo=UTC)]
    auth = InMemoryAuthAdapter()
    sol = auth.obter_por_id("u-sol-1")
    exe = auth.obter_por_id("u-exe-1")
    ges = auth.obter_por_id("u-ges-1")
    assert sol and exe and ges

    gestor = GestorDeChamado(
        InMemoryRepositorioChamado(), InMemoryCatalogoAdapter(), AvaliadorDePrioridade(),
        GeradorProtocoloUnifap(lambda: relogio_atual[0]),
        BackgroundNotificationService([], DiretorioDestinatariosInstitucional(auth)),
        relogio=lambda: relogio_atual[0],
        prazo_reabertura=timedelta(days=7),
    )
    ch = gestor.abrir_chamado(AbrirChamadoRequest.model_validate(CHAMADO_VALIDO), sol)
    gestor.atribuir(ch.protocolo, exe.id, ges, None)
    gestor.iniciar_atendimento(ch.protocolo, exe)
    gestor.resolver(ch.protocolo, "Problema resolvido completamente.", exe)

    # Antes do prazo: nada fecha
    relogio_atual[0] += timedelta(days=5)
    assert gestor.fechar_resolvidos_expirados() == 0

    # Após 7 dias: fecha automaticamente
    relogio_atual[0] += timedelta(days=3)
    assert gestor.fechar_resolvidos_expirados() == 1
    atualizado = gestor.obter_chamado(ch.protocolo, ges)
    assert atualizado.status is StatusChamado.FECHADO


# ---------------------------------------------------------------------- Integridade Arquitetural
def test_isolamento_modular_parnas_sem_imports_concretos_entre_modulos() -> None:
    """Nenhum módulo em src/modules/<A> pode importar implementações concretas de src/modules/<B>."""
    import ast

    raiz = Path(__file__).resolve().parents[1] / "src" / "modules"
    proibidos = {"repository", "service", "gestor_service", "storage_service", "adapters"}
    violacoes: list[str] = []

    for arquivo in raiz.rglob("*.py"):
        modulo_atual = arquivo.relative_to(raiz).parts[0]
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            alvos: list[str] = []
            if isinstance(no, ast.ImportFrom) and no.module:
                alvos.append(no.module)
            elif isinstance(no, ast.Import):
                alvos.extend(alias.name for alias in no.names)
            for alvo in alvos:
                partes = alvo.split(".")
                if len(partes) >= 4 and partes[:2] == ["src", "modules"]:
                    modulo_alvo, submodulo = partes[2], partes[3]
                    if modulo_alvo != modulo_atual and submodulo in proibidos:
                        violacoes.append(f"{arquivo.relative_to(raiz)} -> {alvo}")

    assert violacoes == [], f"Violações de isolamento modular: {violacoes}"

