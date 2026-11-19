"""RF15 / UC08: agregações por sala/equipamento e Tempo Médio de Resolução (TMR)."""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from statistics import fmean

from src.modules.chamados.domain.value_objects import agora_utc
from src.modules.chamados.interfaces import ChamadoSnapshot, FiltroChamados, IConsultaChamados
from src.modules.relatorios.exporters import exportar_csv, exportar_pdf
from src.modules.relatorios.interfaces import (
    AgregadoDTO,
    ArquivoExportado,
    FiltroRelatorioDTO,
    FormatoExportacao,
    RelatorioHistoricoDTO,
)


def _horas_resolucao(s: ChamadoSnapshot) -> float | None:
    if s.resolvido_em is None:
        return None
    return (s.resolvido_em - s.criado_em).total_seconds() / 3600


def calcular_tmr(snapshots: Iterable[ChamadoSnapshot]) -> float | None:
    horas = [h for s in snapshots if (h := _horas_resolucao(s)) is not None]
    return round(fmean(horas), 2) if horas else None


def _agregar(snapshots: Sequence[ChamadoSnapshot],
             chave: Callable[[ChamadoSnapshot], str]) -> list[AgregadoDTO]:
    grupos: dict[str, list[ChamadoSnapshot]] = defaultdict(list)
    for s in snapshots:
        grupos[chave(s)].append(s)
    return sorted(
        (AgregadoDTO(chave=k, total=len(v),
                     resolvidos=sum(1 for s in v if s.resolvido_em is not None),
                     reaberturas=sum(s.reaberturas for s in v), tmr_horas=calcular_tmr(v))
         for k, v in grupos.items()),
        key=lambda a: (-a.total, a.chave))


class ServicoRelatorios:
    def __init__(self, consulta: IConsultaChamados,
                 relogio: Callable[[], datetime] = agora_utc) -> None:
        self._consulta = consulta
        self._relogio = relogio

    def gerar_historico(self, filtro: FiltroRelatorioDTO) -> RelatorioHistoricoDTO:
        snaps = self._consulta.snapshots(FiltroChamados(
            local_id=filtro.local_id, categoria_id=filtro.categoria_id,
            criado_de=filtro.data_inicio, criado_ate=filtro.data_fim))
        notas = [s.nota_avaliacao for s in snaps if s.nota_avaliacao is not None]
        return RelatorioHistoricoDTO(
            gerado_em=self._relogio(),
            total_chamados=len(snaps),
            por_status=dict(Counter(s.status.value for s in snaps)),
            por_prioridade=dict(Counter(s.prioridade.value for s in snaps)),
            por_local=_agregar(snaps, lambda s: s.local_id),
            por_equipamento=_agregar(
                snaps, lambda s: f"{s.categoria_id}/{s.equipamento or 'GERAL'}"),
            tmr_geral_horas=calcular_tmr(snaps),
            media_avaliacao=round(fmean(notas), 2) if notas else None,
        )

    def exportar(self, filtro: FiltroRelatorioDTO,
                 formato: FormatoExportacao) -> ArquivoExportado:
        relatorio = self.gerar_historico(filtro)
        carimbo = relatorio.gerado_em.strftime("%Y%m%d%H%M%S")
        if formato is FormatoExportacao.CSV:
            return ArquivoExportado(nome=f"relatorio_{carimbo}.csv",
                                    media_type="text/csv; charset=utf-8",
                                    conteudo=exportar_csv(relatorio))
        return ArquivoExportado(nome=f"relatorio_{carimbo}.pdf", media_type="application/pdf",
                                conteudo=exportar_pdf(relatorio))
