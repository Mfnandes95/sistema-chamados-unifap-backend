from src.modules.autenticacao.service import InMemoryAuthAdapter
from src.modules.notificacoes.adapters import InMemoryPushAdapter, InMemorySmtpAdapter
from src.modules.notificacoes.interfaces import GRUPO_GESTORES, EventoNotificacao, TipoEvento
from src.modules.notificacoes.service import (
    BackgroundNotificationService,
    DiretorioDestinatariosInstitucional,
)


async def test_falha_de_canal_nao_bloqueia_outros() -> None:
    smtp, push = InMemorySmtpAdapter(falhar=True), InMemoryPushAdapter()
    diretorio = DiretorioDestinatariosInstitucional(InMemoryAuthAdapter())
    svc = BackgroundNotificationService([smtp, push], diretorio)
    svc.publicar(EventoNotificacao(TipoEvento.CHAMADO_ABERTO, "UNIFAP-202611-000001",
                                   ("u-sol-1", "u-exe-1"), "teste"))
    assert await svc.processar_pendentes() == 2
    assert len(push.enviadas) == 2 and len(svc.falhas()) == 2
    assert svc.quantidade_pendentes() == 0


async def test_resolucao_email_e_grupo_gestores_f01() -> None:
    smtp, push = InMemorySmtpAdapter(), InMemoryPushAdapter()
    diretorio = DiretorioDestinatariosInstitucional(InMemoryAuthAdapter())
    svc = BackgroundNotificationService([smtp, push], diretorio)
    # u-sol-2 tem vínculo inativo e não deve receber notificação
    svc.publicar(EventoNotificacao(TipoEvento.CHAMADO_ABERTO, "UNIFAP-202611-000001",
                                   ("u-sol-1", "u-sol-2", GRUPO_GESTORES), "novo"))
    assert await svc.processar_pendentes() == 4  # 2 ativos x 2 canais
    emails = {m.destino for m in smtp.enviadas}
    assert emails == {"ana@unifap.br", "fabio@unifap.br"}
    push_ids = {m.destino for m in push.enviadas}
    assert push_ids == {"u-sol-1", "u-ges-1"}
