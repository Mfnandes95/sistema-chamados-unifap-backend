"""Benchmark do caso de uso de abertura (alvo: < 15 ms por operação em memória)."""

from typing import Any

from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.autenticacao.service import InMemoryAuthAdapter
from src.modules.catalogo_locais.service import InMemoryCatalogoAdapter
from src.modules.chamados.domain.avaliador_prioridade import AvaliadorDePrioridade
from src.modules.chamados.domain.value_objects import GeradorProtocoloUnifap
from src.modules.chamados.gestor_service import GestorDeChamado
from src.modules.chamados.repository import InMemoryRepositorioChamado
from src.modules.chamados.schemas import AbrirChamadoRequest
from src.modules.notificacoes.service import (
    BackgroundNotificationService,
    DiretorioDestinatariosInstitucional,
)
from tests.conftest import CHAMADO_VALIDO


def test_benchmark_abertura(benchmark: Any) -> None:
    diretorio = DiretorioDestinatariosInstitucional(InMemoryAuthAdapter())
    gestor = GestorDeChamado(InMemoryRepositorioChamado(), InMemoryCatalogoAdapter(),
                             AvaliadorDePrioridade(), GeradorProtocoloUnifap(),
                             BackgroundNotificationService([], diretorio))
    ator = UsuarioAutenticado(id="u", matricula="20230001", nome="A", email="a@unifap.br",
                              perfil=Perfil.SOLICITANTE, vinculo_ativo=True)
    dados = AbrirChamadoRequest.model_validate(CHAMADO_VALIDO)
    benchmark(gestor.abrir_chamado, dados, ator)
    assert benchmark.stats.stats.mean < 0.015
