from typing import Protocol

from src.modules.autenticacao.schemas import UsuarioAutenticado
from src.modules.chamados.domain.entities import Chamado
from src.modules.triagem.schemas import AtribuicaoDTO, FiltroFilaDTO, ReencaminhamentoDTO


class IServicoTriagem(Protocol):
    def listar_fila(self, filtro: FiltroFilaDTO, ator: UsuarioAutenticado) -> list[Chamado]: ...

    def atribuir(self, protocolo: str, dados: AtribuicaoDTO,
                 ator: UsuarioAutenticado) -> Chamado: ...

    def reencaminhar(self, protocolo: str, dados: ReencaminhamentoDTO,
                     ator: UsuarioAutenticado) -> Chamado: ...
