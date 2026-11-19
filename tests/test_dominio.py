from datetime import UTC, datetime

import pytest

from src.core.exceptions import TransicaoInvalida, ValidacaoDominio
from src.modules.catalogo_locais.schemas import TipoLocal
from src.modules.catalogo_locais.service import InMemoryCatalogoAdapter
from src.modules.chamados.domain.avaliador_prioridade import (
    AvaliadorDePrioridade,
    CriteriosPrioridade,
)
from src.modules.chamados.domain.entities import Prioridade, StatusChamado
from src.modules.chamados.domain.state_machine import MaquinaEstadosChamado
from src.modules.chamados.domain.value_objects import GeradorProtocoloUnifap, Protocolo
from src.modules.evidencias.storage_service import assinatura_confere, validar_metadados
from src.core.exceptions import ArquivoInvalido


def test_protocolo_formato_e_sequencia_mensal() -> None:
    datas = iter([datetime(2026, 11, 1, tzinfo=UTC)] * 2 + [datetime(2026, 12, 1, tzinfo=UTC)])
    g = GeradorProtocoloUnifap(lambda: next(datas))
    assert g.gerar().valor == "UNIFAP-202611-000001"
    assert g.gerar().valor == "UNIFAP-202611-000002"
    assert g.gerar().valor == "UNIFAP-202612-000001"


@pytest.mark.parametrize("valor", ["UNIFAP-202613-000001", "UNIFAP-2026-1", "X-202601-000001"])
def test_protocolo_invalido(valor: str) -> None:
    with pytest.raises(ValueError):
        Protocolo(valor)


@pytest.mark.parametrize(("atual", "novo", "ok"), [
    (StatusChamado.ABERTO, StatusChamado.ATRIBUIDO, True),
    (StatusChamado.ABERTO, StatusChamado.RESOLVIDO, False),
    (StatusChamado.EM_ATENDIMENTO, StatusChamado.RESOLVIDO, True),
    (StatusChamado.RESOLVIDO, StatusChamado.REABERTO, True),
    (StatusChamado.FECHADO, StatusChamado.REABERTO, False),
    (StatusChamado.CANCELADO, StatusChamado.ABERTO, False),
])
def test_maquina_estados(atual: StatusChamado, novo: StatusChamado, ok: bool) -> None:
    assert MaquinaEstadosChamado.pode_transitar(atual, novo) is ok
    if not ok:
        with pytest.raises(TransicaoInvalida):
            MaquinaEstadosChamado.validar(atual, novo)


@pytest.mark.parametrize(("crit", "tipo", "aulas", "pessoas", "esperado"), [
    (1, TipoLocal.SALA, False, 0, Prioridade.BAIXA),
    (2, TipoLocal.SALA, False, 0, Prioridade.MEDIA),
    (2, TipoLocal.LABORATORIO, True, 0, Prioridade.ALTA),
    (3, TipoLocal.AUDITORIO, True, 100, Prioridade.CRITICA),
])
def test_avaliador_prioridade(crit: int, tipo: TipoLocal, aulas: bool, pessoas: int,
                              esperado: Prioridade) -> None:
    assert AvaliadorDePrioridade().avaliar(
        CriteriosPrioridade(crit, tipo, aulas, pessoas)) is esperado


def test_catalogo_rd01() -> None:
    cat = InMemoryCatalogoAdapter()
    assert cat.validar_local("BL1-T-S101").tipo is TipoLocal.SALA
    with pytest.raises(ValidacaoDominio):
        cat.validar_local("INEXISTENTE")
    with pytest.raises(ValidacaoDominio):
        cat.validar_categoria("ELETRICA", "PROJETOR")


def test_validacao_mime() -> None:
    assert validar_metadados("foto.PNG", "image/png") == ".png"
    with pytest.raises(ArquivoInvalido):
        validar_metadados("script.exe", "application/octet-stream")
    with pytest.raises(ArquivoInvalido):
        validar_metadados("foto.png", "image/jpeg")
    assert assinatura_confere("video/mp4", b"\x00\x00\x00\x18ftypmp42")
    assert not assinatura_confere("image/png", b"GIF89a")
