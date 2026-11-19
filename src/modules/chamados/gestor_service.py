"""CRC 1: GestorDeChamado — orquestrador central.

Não contém regras de pontuação, persistência ou envio de mensagens: apenas
coordena as dependências injetadas no construtor (prevenção de God Class).
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from src.core.exceptions import (
    AcessoNegado,
    ConflitoConcorrencia,
    RecursoNaoEncontrado,
    RegraNegocioViolada,
)
from src.modules.autenticacao.schemas import Perfil, UsuarioAutenticado
from src.modules.catalogo_locais.interfaces import IValidadorCatalogo
from src.modules.chamados.domain.avaliador_prioridade import CriteriosPrioridade
from src.modules.chamados.domain.entities import (
    Avaliacao,
    Chamado,
    Comentario,
    Evidencia,
    RegistroAuditoria,
    StatusChamado,
)
from src.modules.chamados.domain.state_machine import ESTADOS_TERMINAIS, MaquinaEstadosChamado
from src.modules.chamados.domain.value_objects import agora_utc
from src.modules.chamados.interfaces import (
    ChamadoSnapshot,
    FiltroChamados,
    IAvaliadorPrioridade,
    IGeradorProtocolo,
    IRepositorioChamado,
    Pagina,
)
from src.modules.chamados.schemas import AbrirChamadoRequest
from src.modules.notificacoes.interfaces import (
    GRUPO_GESTORES,
    EventoNotificacao,
    IPublicadorEventos,
    TipoEvento,
)

S = StatusChamado
_SISTEMA_ATOR_ID = "SISTEMA"


class GestorDeChamado:
    def __init__(
        self,
        repositorio: IRepositorioChamado,
        catalogo: IValidadorCatalogo,
        avaliador: IAvaliadorPrioridade,
        gerador_protocolo: IGeradorProtocolo,
        publicador: IPublicadorEventos,
        relogio: Callable[[], datetime] = agora_utc,
        prazo_reabertura: timedelta = timedelta(days=7),
        max_reaberturas: int = 3,
        max_evidencias: int = 10,
    ) -> None:
        self._repo = repositorio
        self._catalogo = catalogo
        self._avaliador = avaliador
        self._gerador = gerador_protocolo
        self._publicador = publicador
        self._relogio = relogio
        self._prazo_reabertura = prazo_reabertura
        self._max_reaberturas = max_reaberturas
        self._max_evidencias = max_evidencias

    # ------------------------------------------------------------------ RF02
    def abrir_chamado(self, dados: AbrirChamadoRequest, ator: UsuarioAutenticado) -> Chamado:
        # F04 / V03: validação de perfil e vínculo também no domínio.
        self._exigir_ativo(ator)
        if ator.perfil is not Perfil.SOLICITANTE:
            raise AcessoNegado("Somente solicitantes podem abrir chamados.")
        local = self._catalogo.validar_local(dados.local_id)
        categoria = self._catalogo.validar_categoria(dados.categoria_id, dados.equipamento)
        prioridade = self._avaliador.avaliar(CriteriosPrioridade(
            criticidade_categoria=categoria.criticidade, tipo_local=local.tipo,
            impacta_aulas=dados.impacta_aulas, pessoas_afetadas=dados.pessoas_afetadas))
        agora = self._relogio()
        chamado = Chamado(
            protocolo=self._gerador.gerar().valor, titulo=dados.titulo,
            descricao=dados.descricao, solicitante_id=ator.id, local_id=local.id,
            categoria_id=categoria.id, equipamento=dados.equipamento, prioridade=prioridade,
            criado_em=agora, atualizado_em=agora, impacta_aulas=dados.impacta_aulas,
            pessoas_afetadas=dados.pessoas_afetadas, versao=1)
        self._repo.salvar(chamado, versao_esperada=0)
        self._auditar(chamado, ator.id, "ABERTURA", None, f"Prioridade {prioridade.value}")
        self._notificar(TipoEvento.CHAMADO_ABERTO, chamado, (ator.id, GRUPO_GESTORES),
                        f"Chamado {chamado.protocolo} aberto.")
        return chamado

    # ------------------------------------------------------------------ RF04
    def obter_chamado(self, protocolo: str, ator: UsuarioAutenticado) -> Chamado:
        chamado = self._carregar(protocolo)
        self._verificar_visibilidade(chamado, ator)
        return chamado

    def listar_chamados(self, filtro: FiltroChamados, ator: UsuarioAutenticado,
                        pagina: Pagina = Pagina()) -> list[Chamado]:
        if ator.perfil is Perfil.SOLICITANTE:
            filtro = replace(filtro, solicitante_id=ator.id)
        elif ator.perfil is Perfil.EXECUTOR:
            filtro = replace(filtro, executor_id=ator.id)
        ordenados = sorted(self._repo.listar(filtro), key=lambda c: c.criado_em, reverse=True)
        return pagina.aplicar(ordenados)

    # ------------------------------------------------------------------ RF05
    def comentar(self, protocolo: str, texto: str, interno: bool,
                 ator: UsuarioAutenticado) -> Comentario:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        if chamado.status in ESTADOS_TERMINAIS:
            raise RegraNegocioViolada("Chamado encerrado não aceita comentários.")
        if interno and ator.perfil is Perfil.SOLICITANTE:
            raise AcessoNegado("Solicitantes não podem criar comentários internos.")
        versao_anterior = chamado.versao
        comentario = Comentario(str(uuid.uuid4()), ator.id, ator.perfil, texto, interno,
                                self._relogio())
        chamado.comentarios.append(comentario)
        chamado.atualizado_em = comentario.criado_em
        chamado.versao = versao_anterior + 1
        self._repo.salvar(chamado, versao_anterior)
        self._auditar(chamado, ator.id, "COMENTARIO_INTERNO" if interno else "COMENTARIO",
                      chamado.status, None, visivel_solicitante=not interno)
        if not interno:
            destinos = tuple(d for d in (chamado.solicitante_id, chamado.executor_id)
                             if d and d != ator.id)
            self._notificar(TipoEvento.COMENTARIO_ADICIONADO, chamado, destinos,
                            f"Novo comentário em {chamado.protocolo}.")
        return comentario

    # ------------------------------------------------------------------ RF08/RF10
    def iniciar_atendimento(self, protocolo: str, ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        self._exigir_executor_responsavel(chamado, ator)
        versao_anterior = chamado.versao
        anterior = MaquinaEstadosChamado.transitar(chamado, S.EM_ATENDIMENTO, self._relogio())
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "INICIO_ATENDIMENTO",
                                         anterior, None, TipoEvento.STATUS_ALTERADO,
                                         (chamado.solicitante_id,))

    def resolver(self, protocolo: str, solucao: str, ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        self._exigir_executor_responsavel(chamado, ator)
        versao_anterior = chamado.versao
        agora = self._relogio()
        anterior = MaquinaEstadosChamado.transitar(chamado, S.RESOLVIDO, agora)
        chamado.resolvido_em = agora
        chamado.comentarios.append(Comentario(str(uuid.uuid4()), ator.id, ator.perfil,
                                              f"Solução: {solucao}", False, agora))
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "RESOLUCAO", anterior,
                                         solucao, TipoEvento.CHAMADO_RESOLVIDO,
                                         (chamado.solicitante_id,))

    # ------------------------------------------------------------------ RF11
    def avaliar(self, protocolo: str, nota: int, comentario: str | None,
                ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        self._exigir_dono(chamado, ator)
        versao_anterior = chamado.versao
        agora = self._relogio()
        anterior = MaquinaEstadosChamado.transitar(chamado, S.FECHADO, agora)
        chamado.avaliacao = Avaliacao(nota, comentario, agora)
        chamado.fechado_em = agora
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "AVALIACAO_FECHAMENTO",
                                         anterior, f"Nota {nota}", TipoEvento.CHAMADO_FECHADO,
                                         _ids(chamado.executor_id))

    # ------------------------------------------------------------------ RF13
    def reabrir(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        self._exigir_dono(chamado, ator)
        versao_anterior = chamado.versao
        agora = self._relogio()
        if chamado.status is S.RESOLVIDO:
            if chamado.resolvido_em and agora - chamado.resolvido_em > self._prazo_reabertura:
                raise RegraNegocioViolada("Prazo para reabertura expirado.")
            if chamado.reaberturas >= self._max_reaberturas:
                raise RegraNegocioViolada("Limite de reaberturas atingido.")
        anterior = MaquinaEstadosChamado.transitar(chamado, S.REABERTO, agora)
        chamado.reaberturas += 1
        chamado.resolvido_em = None
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "REABERTURA", anterior,
                                         motivo, TipoEvento.CHAMADO_REABERTO,
                                         (*_ids(chamado.executor_id), GRUPO_GESTORES))

    def cancelar(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        if ator.perfil is not Perfil.GESTOR:
            self._exigir_dono(chamado, ator)
        versao_anterior = chamado.versao
        anterior = MaquinaEstadosChamado.transitar(chamado, S.CANCELADO, self._relogio())
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "CANCELAMENTO",
                                         anterior, motivo, TipoEvento.STATUS_ALTERADO,
                                         (chamado.solicitante_id, *_ids(chamado.executor_id)))

    # ------------------------------------------------------------------ RF14
    def historico(self, protocolo: str, ator: UsuarioAutenticado) -> tuple[RegistroAuditoria, ...]:
        self.obter_chamado(protocolo, ator)
        registros = self._repo.listar_auditoria(protocolo)
        if ator.perfil is Perfil.SOLICITANTE:
            registros = tuple(r for r in registros if r.visivel_solicitante)
        return registros

    # ------------------------------------------------------------------ F02: fechamento automático
    def fechar_resolvidos_expirados(self) -> int:
        agora = self._relogio()
        fechados = 0
        for chamado in self._repo.listar(FiltroChamados(status=S.RESOLVIDO)):
            if (chamado.resolvido_em is None
                    or agora - chamado.resolvido_em <= self._prazo_reabertura):
                continue
            versao_anterior = chamado.versao
            anterior = MaquinaEstadosChamado.transitar(chamado, S.FECHADO, agora)
            chamado.fechado_em = agora
            try:
                self._persistir_transicao(
                    chamado, versao_anterior, _SISTEMA_ATOR_ID, "FECHAMENTO_AUTOMATICO",
                    anterior, "Prazo de reabertura expirado sem contestação.",
                    TipoEvento.CHAMADO_FECHADO, (chamado.solicitante_id,))
                fechados += 1
            except ConflitoConcorrencia:
                # Chamado foi avaliado ou reaberto concorrentemente; ignora.
                continue
        return fechados

    # ------------------------------------------------------------------ Triagem (IOperacoesTriagem)
    def listar_fila(self, filtro: FiltroChamados, pagina: Pagina = Pagina()) -> list[Chamado]:
        ordenados = sorted(self._repo.listar(filtro),
                           key=lambda c: (-c.prioridade.peso, c.criado_em))
        return pagina.aplicar(ordenados)

    def atribuir(self, protocolo: str, executor_id: str, ator: UsuarioAutenticado,
                 observacao: str | None) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self._carregar(protocolo)
        versao_anterior = chamado.versao
        anterior = MaquinaEstadosChamado.transitar(chamado, S.ATRIBUIDO, self._relogio())
        chamado.executor_id = executor_id
        # V11: observação interna do gestor não vaza para o solicitante.
        chamado = self._persistir_transicao(
            chamado, versao_anterior, ator.id, "ATRIBUICAO", anterior,
            f"Executor {executor_id}", TipoEvento.CHAMADO_ATRIBUIDO,
            (executor_id, chamado.solicitante_id))
        if observacao:
            self._auditar(chamado, ator.id, "OBSERVACAO_ATRIBUICAO", anterior, observacao,
                          visivel_solicitante=False)
        return chamado

    def reencaminhar(self, protocolo: str, motivo: str, ator: UsuarioAutenticado) -> Chamado:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        self._exigir_executor_responsavel(chamado, ator)
        versao_anterior = chamado.versao
        anterior = MaquinaEstadosChamado.transitar(chamado, S.ABERTO, self._relogio())
        chamado.executor_id = None
        return self._persistir_transicao(chamado, versao_anterior, ator.id, "REENCAMINHAMENTO",
                                         anterior, motivo, TipoEvento.CHAMADO_REENCAMINHADO,
                                         (GRUPO_GESTORES,))

    # ------------------------------------------------------------------ Evidências
    def verificar_pode_anexar(self, protocolo: str, ator: UsuarioAutenticado) -> None:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        if chamado.status in ESTADOS_TERMINAIS:
            raise RegraNegocioViolada("Chamado encerrado não aceita evidências.")
        if len(chamado.evidencias) >= self._max_evidencias:
            raise RegraNegocioViolada(
                f"Limite de {self._max_evidencias} evidências por chamado atingido.")

    def registrar_evidencia(self, protocolo: str, evidencia: Evidencia,
                            ator: UsuarioAutenticado) -> None:
        self._exigir_ativo(ator)
        chamado = self.obter_chamado(protocolo, ator)
        if chamado.status in ESTADOS_TERMINAIS:
            raise RegraNegocioViolada("Chamado encerrado não aceita evidências.")
        if len(chamado.evidencias) >= self._max_evidencias:
            raise RegraNegocioViolada(
                f"Limite de {self._max_evidencias} evidências por chamado atingido.")
        versao_anterior = chamado.versao
        chamado.evidencias.append(evidencia)
        chamado.atualizado_em = evidencia.enviado_em
        chamado.versao = versao_anterior + 1
        self._repo.salvar(chamado, versao_anterior)
        self._auditar(chamado, ator.id, "EVIDENCIA", chamado.status, evidencia.nome_arquivo)

    def obter_evidencia(self, protocolo: str, evidencia_id: str,
                        ator: UsuarioAutenticado) -> Evidencia:
        chamado = self.obter_chamado(protocolo, ator)
        for ev in chamado.evidencias:
            if ev.id == evidencia_id:
                return ev
        raise RecursoNaoEncontrado("Evidência não encontrada.")

    # ------------------------------------------------------------------ Relatórios
    def snapshots(self, filtro: FiltroChamados) -> Sequence[ChamadoSnapshot]:
        return tuple(
            ChamadoSnapshot(c.protocolo, c.local_id, c.categoria_id, c.equipamento, c.status,
                            c.prioridade, c.criado_em, c.resolvido_em,
                            c.avaliacao.nota if c.avaliacao else None, c.reaberturas)
            for c in self._repo.listar(filtro)
        )

    # ------------------------------------------------------------------ internos
    def _carregar(self, protocolo: str) -> Chamado:
        chamado = self._repo.obter(protocolo)
        if chamado is None:
            raise RecursoNaoEncontrado(f"Chamado {protocolo} não encontrado.")
        return chamado

    @staticmethod
    def _exigir_ativo(ator: UsuarioAutenticado) -> None:
        if not ator.vinculo_ativo:
            raise AcessoNegado("RN02: vínculo institucional inativo.")

    @staticmethod
    def _verificar_visibilidade(chamado: Chamado, ator: UsuarioAutenticado) -> None:
        if ator.perfil in (Perfil.GESTOR, Perfil.ADMIN):
            return
        if ator.perfil is Perfil.SOLICITANTE and chamado.solicitante_id == ator.id:
            return
        if ator.perfil is Perfil.EXECUTOR and chamado.executor_id == ator.id:
            return
        # V07: 404 em vez de 403 evita enumeração de protocolos alheios.
        raise RecursoNaoEncontrado(f"Chamado {chamado.protocolo} não encontrado.")

    @staticmethod
    def _exigir_dono(chamado: Chamado, ator: UsuarioAutenticado) -> None:
        if ator.perfil is not Perfil.SOLICITANTE or chamado.solicitante_id != ator.id:
            raise AcessoNegado("Apenas o solicitante do chamado pode executar esta ação.")

    @staticmethod
    def _exigir_executor_responsavel(chamado: Chamado, ator: UsuarioAutenticado) -> None:
        if ator.perfil is not Perfil.EXECUTOR or chamado.executor_id != ator.id:
            raise AcessoNegado("Apenas o executor responsável pode executar esta ação.")

    def _persistir_transicao(self, chamado: Chamado, versao_anterior: int, ator_id: str, acao: str,
                             anterior: StatusChamado, detalhe: str | None,
                             evento: TipoEvento, destinos: tuple[str, ...]) -> Chamado:
        chamado.versao = versao_anterior + 1
        self._repo.salvar(chamado, versao_anterior)
        self._auditar(chamado, ator_id, acao, anterior, detalhe)
        self._notificar(evento, chamado, destinos,
                        f"Chamado {chamado.protocolo}: {anterior.value} -> {chamado.status.value}")
        return chamado

    def _auditar(self, chamado: Chamado, ator_id: str, acao: str,
                 anterior: StatusChamado | None, detalhe: str | None,
                 visivel_solicitante: bool = True) -> None:
        self._repo.registrar_auditoria(RegistroAuditoria(
            id=str(uuid.uuid4()), protocolo=chamado.protocolo, ator_id=ator_id, acao=acao,
            status_anterior=anterior, status_novo=chamado.status, detalhe=detalhe,
            registrado_em=self._relogio(), visivel_solicitante=visivel_solicitante))

    def _notificar(self, tipo: TipoEvento, chamado: Chamado, destinos: tuple[str, ...],
                   mensagem: str) -> None:
        if destinos:
            self._publicador.publicar(EventoNotificacao(
                tipo, chamado.protocolo, tuple(dict.fromkeys(destinos)), mensagem,
                self._relogio()))


def _ids(*valores: str | None) -> tuple[str, ...]:
    return tuple(v for v in valores if v)
