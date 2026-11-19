"""D04 / RN04 / C02: separação estrita entre Atribuição (Gestor) e Reencaminhamento (Executor)."""

from src.core.exceptions import AcessoNegado, ValidacaoDominio
from src.modules.autenticacao.interfaces import IAutenticadorInstitucional
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.chamados.domain.entities import Chamado
from src.modules.chamados.domain.state_machine import ESTADOS_TERMINAIS
from src.modules.chamados.interfaces import FiltroChamados, IOperacoesTriagem, Pagina
from src.modules.triagem.schemas import AtribuicaoDTO, FiltroFilaDTO, ReencaminhamentoDTO


class ServicoTriagem:
    def __init__(self, operacoes: IOperacoesTriagem,
                 autenticador: IAutenticadorInstitucional) -> None:
        self._operacoes = operacoes
        self._autenticador = autenticador

    def listar_fila(self, filtro: FiltroFilaDTO, ator: UsuarioAutenticado) -> list[Chamado]:
        if ator.perfil is Perfil.SOLICITANTE:
            raise AcessoNegado("Fila de triagem restrita à equipe técnica.")
        if not ator.vinculo_ativo:
            raise AcessoNegado("RN02: vínculo institucional inativo.")
        executor_id = ator.id if ator.perfil is Perfil.EXECUTOR else filtro.executor_id
        # F03: sem filtro explícito de status, oculta chamados já encerrados.
        excluidos = ESTADOS_TERMINAIS if filtro.status is None else frozenset()
        return self._operacoes.listar_fila(
            FiltroChamados(
                status=filtro.status, status_excluidos=excluidos, prioridade=filtro.prioridade,
                local_id=filtro.local_id, categoria_id=filtro.categoria_id,
                executor_id=executor_id),
            Pagina(limite=filtro.limite, deslocamento=filtro.deslocamento),
        )

    def atribuir(self, protocolo: str, dados: AtribuicaoDTO,
                 ator: UsuarioAutenticado) -> Chamado:
        if ator.perfil not in (Perfil.GESTOR, Perfil.ADMIN):
            raise AcessoNegado("RN04: somente o Gestor ou Administrador atribui chamados.")
        if not ator.vinculo_ativo:
            raise AcessoNegado("RN02: vínculo institucional inativo.")
        executor = self._autenticador.obter_por_id(dados.executor_id)
        if executor is None or executor.perfil is not Perfil.EXECUTOR:
            raise ValidacaoDominio("Executor informado não existe.")
        if not executor.vinculo_ativo:
            raise ValidacaoDominio("Executor com vínculo inativo.")
        return self._operacoes.atribuir(protocolo, executor.id, ator, dados.observacao)

    def reencaminhar(self, protocolo: str, dados: ReencaminhamentoDTO,
                     ator: UsuarioAutenticado) -> Chamado:
        if ator.perfil is not Perfil.EXECUTOR:
            raise AcessoNegado("RN04: somente o Executor responsável reencaminha o chamado.")
        if not ator.vinculo_ativo:
            raise AcessoNegado("RN02: vínculo institucional inativo.")
        return self._operacoes.reencaminhar(protocolo, dados.motivo, ator)
