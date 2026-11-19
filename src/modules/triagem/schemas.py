from pydantic import BaseModel, ConfigDict, Field

from src.modules.chamados.domain.entities import Prioridade, StatusChamado


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FiltroFilaDTO(_Entrada):
    status: StatusChamado | None = None
    prioridade: Prioridade | None = None
    local_id: str | None = None
    categoria_id: str | None = None
    executor_id: str | None = None
    limite: int = Field(default=50, ge=1, le=100)
    deslocamento: int = Field(default=0, ge=0)


class AtribuicaoDTO(_Entrada):
    executor_id: str = Field(min_length=1, max_length=64)
    observacao: str | None = Field(default=None, max_length=500)


class ReencaminhamentoDTO(_Entrada):
    motivo: str = Field(min_length=10, max_length=1000)
