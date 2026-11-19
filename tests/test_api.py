from typing import cast

from httpx import AsyncClient

from src.core.container import Container
from src.modules.notificacoes.service import BackgroundNotificationService
from tests.conftest import CHAMADO_VALIDO

H = dict[str, dict[str, str]]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


async def _abrir(client: AsyncClient, tokens: H) -> str:
    r = await client.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=tokens["solicitante"])
    assert r.status_code == 201, r.text
    return str(r.json()["protocolo"])


async def test_login_invalido_e_me(client: AsyncClient, tokens: H) -> None:
    r = await client.post("/api/v1/auth/login", json={"matricula": "20230001", "senha": "errada123"})
    assert r.status_code == 401
    r = await client.get("/api/v1/auth/me", headers=tokens["gestor"])
    assert r.json()["perfil"] == "GESTOR"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_fluxo_completo(client: AsyncClient, tokens: H, container: Container) -> None:
    protocolo = await _abrir(client, tokens)
    assert protocolo.startswith("UNIFAP-")

    r = await client.get(f"/api/v1/chamados/{protocolo}", headers=tokens["solicitante"])
    assert r.json()["status"] == "ABERTO" and r.json()["prioridade"] == "CRITICA"

    r = await client.get("/api/v1/triagem/fila", headers=tokens["gestor"])
    assert [x["protocolo"] for x in r.json()] == [protocolo]

    r = await client.post(f"/api/v1/triagem/{protocolo}/atribuir",
                          json={"executor_id": "u-exe-1"}, headers=tokens["gestor"])
    assert r.status_code == 200 and r.json()["status"] == "ATRIBUIDO"

    r = await client.post(f"/api/v1/chamados/{protocolo}/comentarios",
                          json={"texto": "Verificar compressor", "interno": True},
                          headers=tokens["executor"])
    assert r.status_code == 201

    r = await client.get(f"/api/v1/chamados/{protocolo}", headers=tokens["solicitante"])
    assert r.json()["comentarios"] == []  # comentário interno oculto

    r = await client.post(f"/api/v1/chamados/{protocolo}/evidencias",
                          files={"arquivo": ("foto.png", PNG, "image/png")},
                          headers=tokens["solicitante"])
    assert r.status_code == 201, r.text

    assert (await client.post(f"/api/v1/chamados/{protocolo}/iniciar",
                              headers=tokens["executor"])).json()["status"] == "EM_ATENDIMENTO"
    r = await client.post(f"/api/v1/chamados/{protocolo}/resolver",
                          json={"solucao": "Troca do capacitor do compressor."},
                          headers=tokens["executor"])
    assert r.json()["status"] == "RESOLVIDO"

    r = await client.post(f"/api/v1/chamados/{protocolo}/reabrir",
                          json={"motivo": "Voltou a desligar sozinho."},
                          headers=tokens["solicitante"])
    assert r.json()["status"] == "REABERTO" and r.json()["reaberturas"] == 1

    await client.post(f"/api/v1/chamados/{protocolo}/iniciar", headers=tokens["executor"])
    await client.post(f"/api/v1/chamados/{protocolo}/resolver",
                      json={"solucao": "Troca da placa eletrônica."}, headers=tokens["executor"])
    r = await client.post(f"/api/v1/chamados/{protocolo}/avaliacao",
                          json={"nota": 5}, headers=tokens["solicitante"])
    assert r.json()["status"] == "FECHADO"

    r = await client.get(f"/api/v1/chamados/{protocolo}/historico", headers=tokens["solicitante"])
    acoes = [x["acao"] for x in r.json()]
    assert "COMENTARIO_INTERNO" not in acoes and acoes[0] == "ABERTURA"
    r = await client.get(f"/api/v1/chamados/{protocolo}/historico", headers=tokens["gestor"])
    assert "COMENTARIO_INTERNO" in [x["acao"] for x in r.json()]

    notif = cast(BackgroundNotificationService, container.notificacoes)
    assert notif.quantidade_pendentes() == 0  # despachadas via BackgroundTasks

    r = await client.get("/api/v1/relatorios/historico", headers=tokens["gestor"])
    rel = r.json()
    assert rel["total_chamados"] == 1 and rel["media_avaliacao"] == 5.0
    r = await client.get("/api/v1/relatorios/exportar?formato=pdf", headers=tokens["gestor"])
    assert r.content.startswith(b"%PDF")
    r = await client.get("/api/v1/relatorios/exportar?formato=csv", headers=tokens["gestor"])
    assert b"BL1-1-LAB1" in r.content


async def test_rbac(client: AsyncClient, tokens: H) -> None:
    protocolo = await _abrir(client, tokens)
    # RN02: vínculo inativo não abre chamado
    r = await client.post("/api/v1/chamados", json=CHAMADO_VALIDO, headers=tokens["inativo"])
    assert r.status_code == 403
    # RN04: executor não atribui; gestor não reencaminha
    r = await client.post(f"/api/v1/triagem/{protocolo}/atribuir",
                          json={"executor_id": "u-exe-1"}, headers=tokens["executor"])
    assert r.status_code == 403
    r = await client.post(f"/api/v1/triagem/{protocolo}/reencaminhar",
                          json={"motivo": "Não é da minha área"}, headers=tokens["gestor"])
    assert r.status_code == 403
    # outro solicitante não enxerga
    r = await client.get(f"/api/v1/chamados/{protocolo}", headers=tokens["solicitante2"])
    assert r.status_code == 404
    # solicitante não acessa relatórios nem fila
    assert (await client.get("/api/v1/relatorios/historico",
                             headers=tokens["solicitante"])).status_code == 403
    assert (await client.get("/api/v1/triagem/fila",
                             headers=tokens["solicitante"])).status_code == 403


async def test_reencaminhamento_devolve_para_fila(client: AsyncClient, tokens: H) -> None:
    protocolo = await _abrir(client, tokens)
    await client.post(f"/api/v1/triagem/{protocolo}/atribuir",
                      json={"executor_id": "u-exe-1"}, headers=tokens["gestor"])
    r = await client.post(f"/api/v1/triagem/{protocolo}/reencaminhar",
                          json={"motivo": "Problema é de rede, não elétrico."},
                          headers=tokens["executor2"])
    assert r.status_code == 404  # V07: não revela existência de chamado alheio
    r = await client.post(f"/api/v1/triagem/{protocolo}/reencaminhar",
                          json={"motivo": "Problema é de rede, não elétrico."},
                          headers=tokens["executor"])
    assert r.json()["status"] == "ABERTO" and r.json()["executor_id"] is None


async def test_validacoes_payload(client: AsyncClient, tokens: H) -> None:
    ruim = {**CHAMADO_VALIDO, "local_id": "SALA-FANTASMA"}
    r = await client.post("/api/v1/chamados", json=ruim, headers=tokens["solicitante"])
    assert r.status_code == 422 and r.json()["erro"] == "VALIDACAO_DOMINIO"
    extra = {**CHAMADO_VALIDO, "prioridade": "CRITICA"}  # cliente não define prioridade
    r = await client.post("/api/v1/chamados", json=extra, headers=tokens["solicitante"])
    assert r.status_code == 422
    r = await client.get("/api/v1/chamados/protocolo-invalido", headers=tokens["gestor"])
    assert r.status_code == 422


async def test_transicao_invalida(client: AsyncClient, tokens: H) -> None:
    protocolo = await _abrir(client, tokens)
    r = await client.post(f"/api/v1/chamados/{protocolo}/avaliacao", json={"nota": 4},
                          headers=tokens["solicitante"])
    assert r.status_code == 409


async def test_evidencia_rejeitada(client: AsyncClient, tokens: H) -> None:
    protocolo = await _abrir(client, tokens)
    url = f"/api/v1/chamados/{protocolo}/evidencias"
    r = await client.post(url, files={"arquivo": ("x.png", b"GIF89a....", "image/png")},
                          headers=tokens["solicitante"])
    assert r.status_code == 415
    r = await client.post(url, files={"arquivo": ("x.exe", b"MZ", "application/x-msdownload")},
                          headers=tokens["solicitante"])
    assert r.status_code == 415
    grande = b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 65)
    r = await client.post(url, files={"arquivo": ("x.png", grande, "image/png")},
                          headers=tokens["solicitante"])
    assert r.status_code == 413
