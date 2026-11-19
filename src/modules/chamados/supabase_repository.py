"""Adaptador Supabase para IRepositorioChamado (persiste nas tabelas do Analista de Dados)."""

import re
import threading
import unicodedata
from datetime import UTC, datetime
from typing import Any

from src.core.exceptions import ConflitoConcorrencia, ValidacaoDominio
from src.core.supabase_client import SupabaseClient
from src.modules.autenticacao.schemas import Perfil
from src.modules.chamados.domain.entities import (
    Avaliacao,
    Chamado,
    Comentario,
    Evidencia,
    Prioridade,
    RegistroAuditoria,
    StatusChamado,
)
from src.modules.chamados.interfaces import FiltroChamados

_STATUS_PARA_DB: dict[StatusChamado, str] = {
    StatusChamado.ABERTO: "aguardando_triagem",
    StatusChamado.ATRIBUIDO: "atribuido",
    StatusChamado.EM_ATENDIMENTO: "em_atendimento",
    StatusChamado.RESOLVIDO: "resolvido",
    StatusChamado.REABERTO: "reencaminhado",
    StatusChamado.FECHADO: "concluido",
    StatusChamado.CANCELADO: "cancelado",
}
_DB_PARA_STATUS: dict[str, StatusChamado] = {v: k for k, v in _STATUS_PARA_DB.items()}

_PRIO_PARA_DB: dict[Prioridade, str] = {
    Prioridade.BAIXA: "baixa",
    Prioridade.MEDIA: "media",
    Prioridade.ALTA: "alta",
    Prioridade.CRITICA: "alta",
}
_DB_PARA_PRIO: dict[str, Prioridade] = {
    "baixa": Prioridade.BAIXA,
    "media": Prioridade.MEDIA,
    "alta": Prioridade.ALTA,
}

_ACAO_PARA_TIPO_EVENTO: dict[str, str] = {
    "ABERTURA": "abertura",
    "ATRIBUICAO": "atribuicao_inicial",
    "OBSERVACAO_ATRIBUICAO": "comentario_interno",
    "REENCAMINHAMENTO": "reencaminhamento",
    "INICIO_ATENDIMENTO": "mudanca_situacao",
    "RESOLUCAO": "mudanca_situacao",
    "REABERTURA": "mudanca_situacao",
    "FECHAMENTO_AUTOMATICO": "mudanca_situacao",
    "AVALIACAO_FECHAMENTO": "avaliacao",
    "CANCELAMENTO": "cancelamento",
    "EVIDENCIA": "evidencia_anexada",
    "COMENTARIO": "comentario_interno",
    "COMENTARIO_INTERNO": "comentario_interno",
}


def _slug_codigo(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").upper()[:40] or "GERAL"


def _parse_dt(valor: str | None) -> datetime | None:
    if not valor:
        return None
    dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _atende(c: Chamado, f: FiltroChamados) -> bool:
    return (
        (f.status is None or c.status is f.status)
        and c.status not in f.status_excluidos
        and (f.prioridade is None or c.prioridade is f.prioridade)
        and (f.solicitante_id is None or c.solicitante_id == f.solicitante_id)
        and (f.executor_id is None or c.executor_id == f.executor_id)
        and (f.local_id is None or c.local_id == f.local_id)
        and (f.categoria_id is None or c.categoria_id == f.categoria_id)
        and (f.criado_de is None or c.criado_em >= f.criado_de)
        and (f.criado_ate is None or c.criado_em <= f.criado_ate)
    )


class SupabaseRepositorioChamado:
    """Cumpre IRepositorioChamado persistindo em `chamados`, `chamado_historico`, etc."""

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client
        self._lock = threading.RLock()
        self._versoes: dict[str, int] = {}

    def _mapas_catalogo(self) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
        ambs = self._client.select("ambientes", {"select": "id,codigo"})
        cats = self._client.select("categorias", {"select": "id,nome"})
        amb_cod_to_uuid = {str(a["codigo"]).upper(): str(a["id"]) for a in ambs}
        amb_uuid_to_cod = {str(a["id"]): str(a["codigo"]).upper() for a in ambs}
        cat_cod_to_uuid = {_slug_codigo(str(c["nome"])): str(c["id"]) for c in cats}
        cat_uuid_to_cod = {str(c["id"]): _slug_codigo(str(c["nome"])) for c in cats}
        return amb_cod_to_uuid, amb_uuid_to_cod, cat_cod_to_uuid, cat_uuid_to_cod

    def _para_entidade(
        self,
        row: dict[str, Any],
        amb_uuid_to_cod: dict[str, str],
        cat_uuid_to_cod: dict[str, str],
        carregar_filhos: bool = False,
    ) -> Chamado:
        chamado_uuid = str(row["id"])
        protocolo = str(row["protocolo"])
        criado = _parse_dt(row.get("criado_em")) or datetime.now(UTC)
        atualizado = _parse_dt(row.get("atualizado_em")) or criado
        concluido = _parse_dt(row.get("concluido_em"))
        status = _DB_PARA_STATUS.get(str(row["status"]), StatusChamado.ABERTO)
        prioridade = _DB_PARA_PRIO.get(str(row["prioridade"]), Prioridade.MEDIA)
        nota = row.get("nota_avaliacao")
        avaliacao = (
            Avaliacao(int(nota), row.get("comentario_avaliacao"), concluido or atualizado)
            if nota is not None else None
        )
        comentarios: list[Comentario] = []
        evidencias: list[Evidencia] = []
        if carregar_filhos:
            for c_row in self._client.select(
                "chamado_comentarios_internos",
                {"select": "*", "chamado_id": f"eq.{chamado_uuid}", "order": "criado_em.asc"},
            ):
                comentarios.append(Comentario(
                    id=str(c_row["id"]),
                    autor_id=str(c_row["autor_id"]),
                    autor_perfil=Perfil.GESTOR,
                    texto=str(c_row["mensagem"]),
                    interno=True,
                    criado_em=_parse_dt(c_row.get("criado_em")) or criado,
                ))
            for e_row in self._client.select(
                "chamado_evidencias",
                {"select": "*", "chamado_id": f"eq.{chamado_uuid}", "order": "criado_em.asc"},
            ):
                evidencias.append(Evidencia(
                    id=str(e_row["id"]),
                    nome_arquivo=str(e_row["nome_arquivo"]),
                    content_type=str(e_row["tipo_mime"]),
                    tamanho_bytes=int(e_row["tamanho_bytes"]),
                    caminho=str(e_row["storage_path"]),
                    enviado_por=str(e_row["enviado_por_id"]),
                    enviado_em=_parse_dt(e_row.get("criado_em")) or criado,
                ))
        versao = self._versoes.setdefault(protocolo, 1)
        descricao = str(row["descricao"])
        titulo = descricao.splitlines()[0][:120] if descricao else f"Chamado {protocolo}"
        return Chamado(
            protocolo=protocolo,
            titulo=titulo,
            descricao=descricao,
            solicitante_id=str(row["solicitante_id"]),
            local_id=amb_uuid_to_cod.get(str(row["ambiente_id"]), str(row["ambiente_id"])),
            categoria_id=cat_uuid_to_cod.get(str(row["categoria_id"]), str(row["categoria_id"])),
            equipamento=None,
            prioridade=prioridade,
            criado_em=criado,
            atualizado_em=atualizado,
            impacta_aulas=bool(row.get("impede_atividade_letiva", False)),
            pessoas_afetadas=0,
            status=status,
            executor_id=str(row["executor_id"]) if row.get("executor_id") else None,
            comentarios=comentarios,
            evidencias=evidencias,
            avaliacao=avaliacao,
            resolvido_em=concluido if status is StatusChamado.RESOLVIDO else None,
            fechado_em=concluido if status is StatusChamado.FECHADO else None,
            reaberturas=0,
            versao=versao,
        )

    def salvar(self, chamado: Chamado, versao_esperada: int) -> None:
        with self._lock:
            existentes = self._client.select(
                "chamados",
                {"select": "id,protocolo,atualizado_em", "protocolo": f"eq.{chamado.protocolo}", "limit": "1"},
            )
            existe = bool(existentes)
            versao_atual = self._versoes.get(chamado.protocolo, 1 if existe else 0)
            if versao_atual != versao_esperada:
                raise ConflitoConcorrencia(
                    f"Chamado {chamado.protocolo} foi alterado por outra operação."
                )
            amb_map, _, cat_map, _ = self._mapas_catalogo()
            amb_uuid = amb_map.get(chamado.local_id.upper())
            cat_uuid = cat_map.get(chamado.categoria_id.upper())
            if amb_uuid is None or cat_uuid is None:
                raise ValidacaoDominio("Local ou categoria não encontrados no catálogo Supabase.")

            concluido_dt = chamado.fechado_em or chamado.resolvido_em
            payload: dict[str, Any] = {
                "protocolo": chamado.protocolo,
                "solicitante_id": chamado.solicitante_id,
                "categoria_id": cat_uuid,
                "ambiente_id": amb_uuid,
                "descricao": chamado.descricao,
                "impede_atividade_letiva": chamado.impacta_aulas,
                "prioridade": _PRIO_PARA_DB[chamado.prioridade],
                "status": _STATUS_PARA_DB[chamado.status],
                "executor_id": chamado.executor_id,
                "nota_avaliacao": chamado.avaliacao.nota if chamado.avaliacao else None,
                "comentario_avaliacao": chamado.avaliacao.comentario if chamado.avaliacao else None,
                "concluido_em": concluido_dt.isoformat() if concluido_dt is not None else None,
                "atualizado_em": chamado.atualizado_em.isoformat(),
            }

            if versao_esperada == 0:
                payload["criado_em"] = chamado.criado_em.isoformat()
                inserido = self._client.insert("chamados", payload)
                chamado_uuid = str(inserido["id"])
                # O trigger BEFORE INSERT do Supabase pode gerar o protocolo oficial (ex.: 2026-000002).
                if inserido.get("protocolo"):
                    chamado.protocolo = str(inserido["protocolo"])
            else:
                chamado_uuid = str(existentes[0]["id"])
                filtros_update = {"id": f"eq.{chamado_uuid}"}
                if existentes[0].get("atualizado_em"):
                    # V25: concorrência otimista distribuída usando `atualizado_em` no Postgres.
                    filtros_update["atualizado_em"] = f"eq.{existentes[0]['atualizado_em']}"
                atualizados = self._client.update("chamados", filtros_update, payload)
                if not atualizados:
                    raise ConflitoConcorrencia(
                        f"Chamado {chamado.protocolo} foi alterado concorrentemente."
                    )

            # Sincroniza comentários internos e evidências recém-adicionados
            if chamado.comentarios:
                exist_c = {
                    str(x["id"]) for x in self._client.select(
                        "chamado_comentarios_internos",
                        {"select": "id", "chamado_id": f"eq.{chamado_uuid}"},
                    )
                }
                for com in chamado.comentarios:
                    if com.interno and com.id not in exist_c:
                        self._client.insert("chamado_comentarios_internos", {
                            "id": com.id,
                            "chamado_id": chamado_uuid,
                            "autor_id": com.autor_id,
                            "mensagem": com.texto,
                            "criado_em": com.criado_em.isoformat(),
                        })

            if chamado.evidencias:
                exist_e = {
                    str(x["id"]) for x in self._client.select(
                        "chamado_evidencias",
                        {"select": "id", "chamado_id": f"eq.{chamado_uuid}"},
                    )
                }
                for ev in chamado.evidencias:
                    if ev.id not in exist_e:
                        self._client.insert("chamado_evidencias", {
                            "id": ev.id,
                            "chamado_id": chamado_uuid,
                            "enviado_por_id": ev.enviado_por,
                            "nome_arquivo": ev.nome_arquivo,
                            "storage_path": ev.caminho,
                            "tipo_mime": ev.content_type,
                            "tamanho_bytes": ev.tamanho_bytes,
                            "etapa": _STATUS_PARA_DB[chamado.status],
                            "criado_em": ev.enviado_em.isoformat(),
                        })

            self._versoes[chamado.protocolo] = chamado.versao

    def obter(self, protocolo: str) -> Chamado | None:
        linhas = self._client.select(
            "chamados", {"select": "*", "protocolo": f"eq.{protocolo}", "limit": "1"}
        )
        if not linhas:
            return None
        _, amb_u2c, _, cat_u2c = self._mapas_catalogo()
        return self._para_entidade(linhas[0], amb_u2c, cat_u2c, carregar_filhos=True)

    def listar(self, filtro: FiltroChamados) -> list[Chamado]:
        linhas = self._client.select("chamados", {"select": "*", "order": "criado_em.desc"})
        _, amb_u2c, _, cat_u2c = self._mapas_catalogo()
        todos = [self._para_entidade(r, amb_u2c, cat_u2c, carregar_filhos=False) for r in linhas]
        return [c for c in todos if _atende(c, filtro)]

    def registrar_auditoria(self, registro: RegistroAuditoria) -> None:
        linhas = self._client.select(
            "chamados",
            {"select": "id,solicitante_id", "protocolo": f"eq.{registro.protocolo}", "limit": "1"},
        )
        if not linhas:
            return
        chamado_uuid = str(linhas[0]["id"])
        autor_id = (
            str(linhas[0]["solicitante_id"])
            if registro.ator_id == "SISTEMA"
            else registro.ator_id
        )
        self._client.insert("chamado_historico", {
            "id": registro.id,
            "chamado_id": chamado_uuid,
            "autor_id": autor_id,
            "papel_no_momento": "gestor" if not registro.visivel_solicitante else "solicitante",
            "tipo_evento": _ACAO_PARA_TIPO_EVENTO.get(registro.acao, "mudanca_situacao"),
            "titulo_evento": registro.acao,
            "detalhe": registro.detalhe,
            "status_anterior": (
                _STATUS_PARA_DB[registro.status_anterior] if registro.status_anterior else None
            ),
            "status_novo": _STATUS_PARA_DB[registro.status_novo],
            "criado_em": registro.registrado_em.isoformat(),
        })

    def listar_auditoria(self, protocolo: str) -> tuple[RegistroAuditoria, ...]:
        linhas = self._client.select(
            "chamados", {"select": "id", "protocolo": f"eq.{protocolo}", "limit": "1"}
        )
        if not linhas:
            return ()
        chamado_uuid = str(linhas[0]["id"])
        eventos = self._client.select(
            "chamado_historico",
            {"select": "*", "chamado_id": f"eq.{chamado_uuid}", "order": "criado_em.asc"},
        )
        saida: list[RegistroAuditoria] = []
        for ev in eventos:
            acao = str(ev.get("titulo_evento") or ev.get("tipo_evento") or "EVENTO")
            visivel = ev.get("tipo_evento") != "comentario_interno"
            sa = ev.get("status_anterior")
            sn = ev.get("status_novo") or "aguardando_triagem"
            saida.append(RegistroAuditoria(
                id=str(ev["id"]),
                protocolo=protocolo,
                ator_id=str(ev["autor_id"]),
                acao=acao,
                status_anterior=_DB_PARA_STATUS.get(str(sa)) if sa else None,
                status_novo=_DB_PARA_STATUS.get(str(sn), StatusChamado.ABERTO),
                detalhe=str(ev["detalhe"]) if ev.get("detalhe") is not None else None,
                registrado_em=_parse_dt(ev.get("criado_em")) or datetime.now(UTC),
                visivel_solicitante=visivel,
            ))
        return tuple(saida)
