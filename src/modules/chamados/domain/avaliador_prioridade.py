"""D06 / RN01 (CRC 2): AvaliadorDePrioridade.

Pontuação = 2*criticidade_categoria + impacto_aulas(2) + laboratorio/auditorio(1)
          + pessoas_afetadas (>=50: 2 | >=10: 1)
Faixas: >=8 CRITICA | >=6 ALTA | >=4 MEDIA | demais BAIXA.
"""

from dataclasses import dataclass

from src.modules.catalogo_locais.schemas import TipoLocal
from src.modules.chamados.domain.entities import Prioridade


@dataclass(frozen=True, slots=True)
class CriteriosPrioridade:
    criticidade_categoria: int
    tipo_local: TipoLocal
    impacta_aulas: bool
    pessoas_afetadas: int


class AvaliadorDePrioridade:
    def pontuar(self, c: CriteriosPrioridade) -> int:
        pontos = 2 * c.criticidade_categoria
        if c.impacta_aulas:
            pontos += 2
        if c.tipo_local in (TipoLocal.LABORATORIO, TipoLocal.AUDITORIO):
            pontos += 1
        if c.pessoas_afetadas >= 50:
            pontos += 2
        elif c.pessoas_afetadas >= 10:
            pontos += 1
        return pontos

    def avaliar(self, criterios: CriteriosPrioridade) -> Prioridade:
        p = self.pontuar(criterios)
        if p >= 8:
            return Prioridade.CRITICA
        if p >= 6:
            return Prioridade.ALTA
        if p >= 4:
            return Prioridade.MEDIA
        return Prioridade.BAIXA
