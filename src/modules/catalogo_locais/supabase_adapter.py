"""Adaptador Supabase para IValidadorCatalogo (RD01)."""

import re
import unicodedata
from collections.abc import Sequence

from src.core.exceptions import ValidacaoDominio
from src.core.supabase_client import SupabaseClient
from src.modules.catalogo_locais.schemas import CategoriaDTO, LocalDTO, TipoLocal


def _slug_codigo(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpo = re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").upper()
    return limpo[:40] or "GERAL"


def _mapear_tipo_local(tipo_ambiente: str) -> TipoLocal:
    t = tipo_ambiente.lower()
    if "laborat" in t:
        return TipoLocal.LABORATORIO
    if "audit" in t:
        return TipoLocal.AUDITORIO
    if "sala" in t:
        return TipoLocal.SALA
    return TipoLocal.AREA_COMUM


def _criticidade_categoria(codigo: str) -> int:
    if "ELETRIC" in codigo:
        return 3
    if any(k in codigo for k in ("REFRIG", "CLIMAT", "TECNOLOGIA", "PREDIAL")):
        return 2
    return 1


class SupabaseCatalogoAdapter:
    """Cumpre IValidadorCatalogo lendo `ambientes`/`andares`/`blocos` e `categorias` do Supabase."""

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    def _carregar_locais(self) -> tuple[dict[str, LocalDTO], dict[str, str]]:
        blocos = {
            str(b["id"]): str(b.get("codigo") or b.get("nome") or "BLOCO")
            for b in self._client.select("blocos", {"select": "id,nome,codigo", "ativo": "eq.true"})
        }
        andares = {
            str(a["id"]): (str(a["bloco_id"]), int(a.get("ordem") or 0))
            for a in self._client.select("andares", {"select": "id,bloco_id,ordem", "ativo": "eq.true"})
        }
        ambientes = self._client.select(
            "ambientes",
            {"select": "id,andar_id,codigo,nome,tipo_ambiente,ativo", "ativo": "eq.true"},
        )
        por_codigo: dict[str, LocalDTO] = {}
        uuid_por_codigo: dict[str, str] = {}
        for amb in ambientes:
            andar_info = andares.get(str(amb["andar_id"]))
            bloco_nome = blocos.get(andar_info[0], "BLOCO") if andar_info else "BLOCO"
            andar_ordem = max(0, min(20, andar_info[1])) if andar_info else 0
            codigo = str(amb["codigo"]).upper()
            dto = LocalDTO(
                id=codigo,
                bloco=bloco_nome,
                andar=andar_ordem,
                nome=str(amb["nome"]),
                tipo=_mapear_tipo_local(str(amb.get("tipo_ambiente") or "")),
            )
            por_codigo[codigo] = dto
            uuid_por_codigo[codigo] = str(amb["id"])
        return por_codigo, uuid_por_codigo

    def _carregar_categorias(self) -> tuple[dict[str, CategoriaDTO], dict[str, str]]:
        linhas = self._client.select(
            "categorias", {"select": "id,nome,ativo", "ativo": "eq.true"}
        )
        por_codigo: dict[str, CategoriaDTO] = {}
        uuid_por_codigo: dict[str, str] = {}
        for row in linhas:
            codigo = _slug_codigo(str(row["nome"]))
            dto = CategoriaDTO(
                id=codigo,
                nome=str(row["nome"]),
                criticidade=_criticidade_categoria(codigo),
                equipamentos=(),
            )
            por_codigo[codigo] = dto
            uuid_por_codigo[codigo] = str(row["id"])
        return por_codigo, uuid_por_codigo

    def validar_local(self, local_id: str) -> LocalDTO:
        locais, _ = self._carregar_locais()
        local = locais.get(local_id.upper())
        if local is None:
            raise ValidacaoDominio(f"RD01: local '{local_id}' não pertence ao catálogo ativo.")
        return local

    def validar_categoria(self, categoria_id: str, equipamento: str | None) -> CategoriaDTO:
        categorias, _ = self._carregar_categorias()
        categoria = categorias.get(categoria_id.upper())
        if categoria is None:
            raise ValidacaoDominio(f"RD01: categoria '{categoria_id}' inexistente ou inativa.")
        if equipamento is not None and categoria.equipamentos and equipamento not in categoria.equipamentos:
            raise ValidacaoDominio(
                f"RD01: equipamento '{equipamento}' não pertence à categoria '{categoria_id}'."
            )
        return categoria

    def listar_locais(
        self, bloco: str | None = None, tipo: TipoLocal | None = None
    ) -> Sequence[LocalDTO]:
        locais, _ = self._carregar_locais()
        return tuple(
            x for x in locais.values()
            if (bloco is None or x.bloco == bloco) and (tipo is None or x.tipo is tipo)
        )

    def listar_categorias(self) -> Sequence[CategoriaDTO]:
        categorias, _ = self._carregar_categorias()
        return tuple(categorias.values())
