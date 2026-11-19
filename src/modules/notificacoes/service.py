"""BackgroundNotificationService (D05, D07/ADR-01, RF12, RN03).

O domínio apenas enfileira eventos (O(1)); o despacho ocorre em
FastAPI BackgroundTasks após a resposta HTTP. Falhas de canal ou de resolução
de destinatários são isoladas e registradas, nunca propagadas ao fluxo principal.
"""

import logging
import threading
from collections import deque
from collections.abc import Sequence

from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.notificacoes.interfaces import (
    GRUPO_GESTORES,
    Destinatario,
    EventoNotificacao,
    FalhaEntrega,
    ICanalNotificacao,
    IDiretorioDestinatarios,
    IFonteUsuarios,
)

logger = logging.getLogger(__name__)


class DiretorioDestinatariosInstitucional:
    """Resolve IDs e grupos simbólicos em destinatários ativos com e-mail (F01)."""

    def __init__(self, fonte: IFonteUsuarios) -> None:
        self._fonte = fonte

    def resolver(self, referencias: Sequence[str]) -> Sequence[Destinatario]:
        resolvidos: dict[str, Destinatario] = {}
        for ref in referencias:
            usuarios: Sequence[UsuarioAutenticado]
            if ref == GRUPO_GESTORES:
                usuarios = self._fonte.listar_por_perfil(Perfil.GESTOR)
            else:
                u = self._fonte.obter_por_id(ref)
                usuarios = (u,) if u is not None else ()
            for usuario in usuarios:
                if usuario.vinculo_ativo:
                    resolvidos.setdefault(usuario.id, Destinatario(usuario.id, usuario.email))
        return tuple(resolvidos.values())


class BackgroundNotificationService:
    def __init__(self, canais: Sequence[ICanalNotificacao], diretorio: IDiretorioDestinatarios,
                 tentativas: int = 2, max_fila: int = 10_000, max_falhas: int = 1_000) -> None:
        self._canais = tuple(canais)
        self._diretorio = diretorio
        self._tentativas = max(1, tentativas)
        self._max_fila = max_fila
        self._fila: deque[EventoNotificacao] = deque()
        self._falhas: deque[FalhaEntrega] = deque(maxlen=max_falhas)
        self._lock = threading.Lock()

    def publicar(self, evento: EventoNotificacao) -> None:
        with self._lock:
            if len(self._fila) >= self._max_fila:  # back-pressure: protege a memória
                descartado = self._fila.popleft()
                logger.error("Fila de notificações cheia; descartado evento de %s",
                             descartado.protocolo)
            self._fila.append(evento)

    def quantidade_pendentes(self) -> int:
        return len(self._fila)

    def falhas(self) -> Sequence[FalhaEntrega]:
        return tuple(self._falhas)

    def _proximo(self) -> EventoNotificacao | None:
        with self._lock:
            return self._fila.popleft() if self._fila else None

    async def processar_pendentes(self) -> int:
        entregues = 0
        while (evento := self._proximo()) is not None:
            try:
                destinatarios = self._diretorio.resolver(evento.destinatarios)
            except Exception as exc:  # noqa: BLE001 - RN03
                logger.warning("Falha ao resolver destinatários de %s: %r", evento.protocolo, exc)
                self._falhas.append(FalhaEntrega("diretorio", "*", evento.protocolo, repr(exc)))
                continue
            for destinatario in destinatarios:
                for canal in self._canais:
                    if await self._enviar_com_retentativa(canal, evento, destinatario):
                        entregues += 1
        return entregues

    async def _enviar_com_retentativa(self, canal: ICanalNotificacao, evento: EventoNotificacao,
                                      destinatario: Destinatario) -> bool:
        ultimo_erro = ""
        for _ in range(self._tentativas):
            try:
                await canal.enviar(evento, destinatario)
                return True
            except Exception as exc:  # noqa: BLE001 - RN03: isolamento total de falhas
                ultimo_erro = repr(exc)
        logger.warning("Falha ao notificar %s via %s: %s", destinatario.id, canal.nome,
                       ultimo_erro)
        self._falhas.append(FalhaEntrega(canal.nome, destinatario.id, evento.protocolo,
                                         ultimo_erro))
        return False
