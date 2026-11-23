from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TipoLocal(StrEnum):
    SALA = "SALA"
    LABORATORIO = "LABORATORIO"
    AUDITORIO = "AUDITORIO"
    AREA_COMUM = "AREA_COMUM"


class LocalDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    bloco: str
    andar: int = Field(ge=0, le=20)
    nome: str
    tipo: TipoLocal
    campus: str | None = None


class CategoriaDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    nome: str
    criticidade: int = Field(ge=1, le=3, description="1=baixa, 2=média, 3=alta")
    equipamentos: tuple[str, ...]


class AndarDTO(BaseModel):
    andar: int
    locais: list[LocalDTO]


class BlocoDTO(BaseModel):
    bloco: str
    andares: list[AndarDTO]
