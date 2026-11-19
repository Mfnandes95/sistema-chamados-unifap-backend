"""DTOs do módulo de chamados com ocultação de comentários internos."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.modules.autenticacao.schemas import Perfil
from src.modules.chamados.domain.entities import (
    Chamado,
    Prioridade,
    RegistroAuditoria,
    StatusChamado,
)

PROTOCOLO_REGEX = r"^(UNIFAP-\d{4}(0[1-9]|1[0-2])-\d{6}|\d{4}-\d{6})$"
Codigo = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_\-]{2,40}$")]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AbrirChamadoRequest(_Entrada):
    titulo: str = Field(min_length=5, max_length=120)
    descricao: str = Field(min_length=10, max_length=2000)
    local_id: Codigo
    categoria_id: Codigo
    equipamento: Codigo | None = None
    impacta_aulas: bool = False
    pessoas_afetadas: int = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def _titulo_diferente_descricao(self) -> "AbrirChamadoRequest":
        if self.titulo.casefold() == self.descricao.casefold():
            raise ValueError("Descrição deve detalhar o problema, não repetir o título.")
        return self


class ComentarioRequest(_Entrada):
    texto: str = Field(min_length=1, max_length=2000)
    interno: bool = False


class ResolverRequest(_Entrada):
    solucao: str = Field(min_length=10, max_length=2000)


class AvaliacaoRequest(_Entrada):
    nota: int = Field(ge=1, le=5)
    comentario: str | None = Field(default=None, max_length=500)


class MotivoRequest(_Entrada):
    motivo: str = Field(min_length=10, max_length=1000)


class FiltroChamadosQuery(_Entrada):
    status: StatusChamado | None = None
    prioridade: Prioridade | None = None
    local_id: str | None = None
    categoria_id: str | None = None
    limite: int = Field(default=50, ge=1, le=100)
    deslocamento: int = Field(default=0, ge=0)


class ComentarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    autor_id: str
    autor_perfil: Perfil
    texto: str
    interno: bool
    criado_em: datetime


class EvidenciaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    nome_arquivo: str
    content_type: str
    tamanho_bytes: int
    enviado_por: str
    enviado_em: datetime


class AvaliacaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    nota: int
    comentario: str | None
    criado_em: datetime


class ChamadoResumoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    protocolo: str
    titulo: str
    status: StatusChamado
    prioridade: Prioridade
    local_id: str
    categoria_id: str
    executor_id: str | None
    criado_em: datetime
    atualizado_em: datetime


class ChamadoResponse(ChamadoResumoResponse):
    descricao: str
    solicitante_id: str
    equipamento: str | None
    impacta_aulas: bool
    pessoas_afetadas: int
    reaberturas: int
    resolvido_em: datetime | None
    fechado_em: datetime | None
    comentarios: list[ComentarioResponse]
    evidencias: list[EvidenciaResponse]
    avaliacao: AvaliacaoResponse | None

    @classmethod
    def de_entidade(cls, chamado: Chamado, perfil: Perfil) -> "ChamadoResponse":
        """Solicitantes nunca recebem comentários internos da equipe técnica."""
        comentarios = [
            ComentarioResponse.model_validate(c) for c in chamado.comentarios
            if not (c.interno and perfil is Perfil.SOLICITANTE)
        ]
        return cls(
            protocolo=chamado.protocolo, titulo=chamado.titulo, status=chamado.status,
            prioridade=chamado.prioridade, local_id=chamado.local_id,
            categoria_id=chamado.categoria_id, executor_id=chamado.executor_id,
            criado_em=chamado.criado_em, atualizado_em=chamado.atualizado_em,
            descricao=chamado.descricao, solicitante_id=chamado.solicitante_id,
            equipamento=chamado.equipamento, impacta_aulas=chamado.impacta_aulas,
            pessoas_afetadas=chamado.pessoas_afetadas, reaberturas=chamado.reaberturas,
            resolvido_em=chamado.resolvido_em, fechado_em=chamado.fechado_em,
            comentarios=comentarios,
            evidencias=[EvidenciaResponse.model_validate(e) for e in chamado.evidencias],
            avaliacao=(AvaliacaoResponse.model_validate(chamado.avaliacao)
                       if chamado.avaliacao else None),
        )


class RegistroAuditoriaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ator_id: str
    acao: str
    status_anterior: StatusChamado | None
    status_novo: StatusChamado
    detalhe: str | None
    registrado_em: datetime

    @classmethod
    def lista(cls, registros: tuple[RegistroAuditoria, ...]) -> list["RegistroAuditoriaResponse"]:
        return [cls.model_validate(r) for r in registros]
