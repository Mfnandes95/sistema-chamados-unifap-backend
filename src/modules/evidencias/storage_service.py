"""RF03: armazenamento de evidências com validação estrita (extensão + MIME + magic bytes + tamanho)."""

import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePath
from typing import Final

import aiofiles
import aiofiles.os

from src.core.exceptions import ArquivoInvalido, ArquivoMuitoGrande
from src.modules.autenticacao.schemas import UsuarioAutenticado
from src.modules.chamados.domain.entities import Evidencia
from src.modules.chamados.domain.value_objects import agora_utc
from src.modules.chamados.interfaces import IRegistroEvidencias
from src.modules.evidencias.interfaces import EvidenciaDTO, LeitorBytes

TAMANHO_BLOCO: Final = 64 * 1024

TIPOS_PERMITIDOS: Final[dict[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
}


def assinatura_confere(content_type: str, cabecalho: bytes) -> bool:
    match content_type:
        case "image/jpeg":
            return cabecalho.startswith(b"\xff\xd8\xff")
        case "image/png":
            return cabecalho.startswith(b"\x89PNG\r\n\x1a\n")
        case "image/webp":
            return cabecalho[:4] == b"RIFF" and cabecalho[8:12] == b"WEBP"
        case "video/mp4":
            return cabecalho[4:8] == b"ftyp"
        case _:
            return False


def sanitizar_nome_arquivo(nome_arquivo: str) -> str:
    """V17: remove caminhos, caracteres de controle e marcadores bidi (ex.: RLO U+202E)."""
    base = PurePath(nome_arquivo).name
    limpo = "".join(ch for ch in base if unicodedata.category(ch) not in ("Cc", "Cf"))
    return limpo.strip()[:255]


def validar_metadados(nome_arquivo: str, content_type: str) -> str:
    """Retorna a extensão normalizada ou lança ArquivoInvalido."""
    nome = sanitizar_nome_arquivo(nome_arquivo)
    extensao = PurePath(nome).suffix.lower()
    esperado = TIPOS_PERMITIDOS.get(extensao)
    if esperado is None:
        raise ArquivoInvalido(f"Extensão '{extensao or '?'}' não permitida.")
    if content_type.lower() != esperado:
        raise ArquivoInvalido(f"MIME '{content_type}' incompatível com '{extensao}'.")
    return extensao


class ServicoArmazenamentoEvidencias:
    def __init__(self, registro: IRegistroEvidencias, diretorio: Path, limite_bytes: int,
                 relogio: Callable[[], datetime] = agora_utc) -> None:
        self._registro = registro
        self._diretorio = diretorio
        self._limite = limite_bytes
        self._relogio = relogio

    async def anexar(self, protocolo: str, nome_arquivo: str, content_type: str,
                     leitor: LeitorBytes, ator: UsuarioAutenticado) -> EvidenciaDTO:
        extensao = validar_metadados(nome_arquivo, content_type)
        self._registro.verificar_pode_anexar(protocolo, ator)

        evidencia_id = str(uuid.uuid4())
        pasta = self._diretorio / protocolo
        await aiofiles.os.makedirs(pasta, exist_ok=True)
        destino = pasta / f"{evidencia_id}{extensao}"
        total = 0
        agora = self._relogio()
        nome_seguro = sanitizar_nome_arquivo(nome_arquivo) or f"{evidencia_id}{extensao}"
        try:
            async with aiofiles.open(destino, "wb") as arquivo:
                primeiro = True
                while bloco := await leitor(TAMANHO_BLOCO):
                    if primeiro and not assinatura_confere(content_type.lower(), bloco[:16]):
                        raise ArquivoInvalido("Conteúdo não corresponde ao tipo declarado.")
                    primeiro = False
                    total += len(bloco)
                    if total > self._limite:
                        raise ArquivoMuitoGrande(f"Arquivo excede {self._limite} bytes.")
                    await arquivo.write(bloco)
            if total == 0:
                raise ArquivoInvalido("Arquivo vazio.")
            # V17: se o registro falhar (ex.: conflito de concorrência ou limite), remove o arquivo.
            self._registro.registrar_evidencia(protocolo, Evidencia(
                evidencia_id, nome_seguro, content_type.lower(), total, str(destino),
                ator.id, agora), ator)
        except BaseException:
            if await aiofiles.os.path.exists(destino):
                await aiofiles.os.remove(destino)
            raise

        return EvidenciaDTO(id=evidencia_id, protocolo=protocolo, nome_arquivo=nome_seguro,
                            content_type=content_type.lower(), tamanho_bytes=total,
                            enviado_em=agora)
