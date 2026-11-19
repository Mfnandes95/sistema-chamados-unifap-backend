from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class FormatoExportacao(StrEnum):
    CSV = "csv"
    PDF = "pdf"


class FiltroRelatorioDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_inicio: datetime | None = None
    data_fim: datetime | None = None
    local_id: str | None = None
    categoria_id: str | None = None

    @field_validator("data_inicio", "data_fim", mode="after")
    @classmethod
    def _garantir_utc(cls, valor: datetime | None) -> datetime | None:
        """V10: normaliza datas sem fuso para UTC, evitando TypeError ao comparar."""
        if valor is None:
            return None
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor.astimezone(UTC)

    @model_validator(mode="after")
    def _intervalo(self) -> "FiltroRelatorioDTO":
        if self.data_inicio and self.data_fim and self.data_inicio > self.data_fim:
            raise ValueError("data_inicio deve ser anterior a data_fim.")
        return self


class AgregadoDTO(BaseModel):
    chave: str
    total: int
    resolvidos: int
    reaberturas: int
    tmr_horas: float | None


class RelatorioHistoricoDTO(BaseModel):
    gerado_em: datetime
    total_chamados: int
    por_status: dict[str, int]
    por_prioridade: dict[str, int]
    por_local: list[AgregadoDTO]
    por_equipamento: list[AgregadoDTO]
    tmr_geral_horas: float | None
    media_avaliacao: float | None


class ArquivoExportado(BaseModel):
    model_config = ConfigDict(frozen=True)

    nome: str
    media_type: str
    conteudo: bytes


class IServicoRelatorios(Protocol):
    def gerar_historico(self, filtro: FiltroRelatorioDTO) -> RelatorioHistoricoDTO: ...

    def exportar(self, filtro: FiltroRelatorioDTO,
                 formato: FormatoExportacao) -> ArquivoExportado: ...
