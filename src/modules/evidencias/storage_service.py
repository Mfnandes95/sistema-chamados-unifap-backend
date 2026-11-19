"""RF03: armazenamento de evidências com validação estrita (extensão + MIME + magic bytes + tamanho).

Suporta envio do dispositivo (celular/PC via multipart) e importação segura de links
públicos do Google Drive (com proteção anti-SSRF por allowlist de ID).
"""

import re
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePath
from typing import Final

import aiofiles
import aiofiles.os
import httpx

from src.core.exceptions import (
    ArquivoInvalido,
    ArquivoMuitoGrande,
    RecursoNaoEncontrado,
    ValidacaoDominio,
)
from src.modules.autenticacao.schemas import UsuarioAutenticado
from src.modules.chamados.domain.entities import Evidencia
from src.modules.chamados.domain.value_objects import agora_utc
from src.modules.chamados.interfaces import IRegistroEvidencias
from src.modules.evidencias.interfaces import ArquivoEvidencia, EvidenciaDTO, LeitorBytes

TAMANHO_BLOCO: Final = 64 * 1024

TIPOS_PERMITIDOS: Final[dict[str, str]] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
}

_EXT_POR_MIME: Final[dict[str, str]] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}

# Anti-SSRF: aceita somente links oficiais do Google Drive e extrai apenas o file_id alfanumérico.
_PADROES_DRIVE: Final = (
    re.compile(r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]{10,64})(?:/.*|\?.*)?$"),
    re.compile(r"^https://drive\.google\.com/open\?id=([A-Za-z0-9_-]{10,64})(?:&.*)?$"),
    re.compile(r"^https://drive\.google\.com/uc\?(?:.*&)?id=([A-Za-z0-9_-]{10,64})(?:&.*)?$"),
)

_HOSTS_REDIRECT_DRIVE: Final = frozenset({
    "drive.google.com",
    "drive.usercontent.google.com",
    "doc-00-00-docs.googleusercontent.com",
})


def extrair_id_google_drive(url: str) -> str:
    """Extrai o file_id de um link do Google Drive ou lança ValidacaoDominio."""
    limpa = url.strip()
    for padrao in _PADROES_DRIVE:
        m = padrao.fullmatch(limpa)
        if m:
            return m.group(1)
    raise ValidacaoDominio(
        "Link do Google Drive inválido. Use um link no formato "
        "https://drive.google.com/file/d/<ID>/view"
    )


def detectar_mime_por_assinatura(cabecalho: bytes) -> str | None:
    if cabecalho.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if cabecalho.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if cabecalho[:4] == b"RIFF" and cabecalho[8:12] == b"WEBP":
        return "image/webp"
    if cabecalho[4:8] == b"ftyp":
        return "video/mp4"
    return None


def assinatura_confere(content_type: str, cabecalho: bytes) -> bool:
    return detectar_mime_por_assinatura(cabecalho) == content_type


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

    async def anexar_google_drive(
        self, protocolo: str, url: str, nome_arquivo: str | None, ator: UsuarioAutenticado
    ) -> EvidenciaDTO:
        file_id = extrair_id_google_drive(url)
        self._registro.verificar_pode_anexar(protocolo, ator)

        url_download = f"https://drive.google.com/uc?export=download&id={file_id}"
        evidencia_id = str(uuid.uuid4())
        pasta = self._diretorio / protocolo
        await aiofiles.os.makedirs(pasta, exist_ok=True)
        temp_destino = pasta / f"{evidencia_id}.tmp"
        destino: Path | None = None
        total = 0
        mime_detectado: str | None = None

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                async with client.stream("GET", url_download) as resp:
                    host_final = (resp.url.host or "").lower()
                    if not (host_final in _HOSTS_REDIRECT_DRIVE
                            or host_final.endswith(".googleusercontent.com")):
                        raise ValidacaoDominio("Redirecionamento fora do domínio do Google Drive.")
                    if resp.status_code != 200:
                        raise ArquivoInvalido(
                            "Não foi possível baixar do Google Drive. Verifique se o link está "
                            "compartilhado como 'Qualquer pessoa com o link'."
                        )
                    async with aiofiles.open(temp_destino, "wb") as arquivo:
                        primeiro = True
                        async for bloco in resp.aiter_bytes(TAMANHO_BLOCO):
                            if not bloco:
                                continue
                            if primeiro:
                                mime_detectado = detectar_mime_por_assinatura(bloco[:16])
                                if mime_detectado is None:
                                    raise ArquivoInvalido(
                                        "O arquivo do Google Drive não é uma imagem (JPG/PNG/WEBP) "
                                        "ou vídeo MP4 acessível publicamente."
                                    )
                                primeiro = False
                            total += len(bloco)
                            if total > self._limite:
                                raise ArquivoMuitoGrande(f"Arquivo excede {self._limite} bytes.")
                            await arquivo.write(bloco)

            if total == 0 or mime_detectado is None:
                raise ArquivoInvalido("Arquivo vazio no Google Drive.")

            extensao = _EXT_POR_MIME[mime_detectado]
            destino = pasta / f"{evidencia_id}{extensao}"
            await aiofiles.os.rename(temp_destino, destino)

            base_nome = sanitizar_nome_arquivo(nome_arquivo or "") or f"google-drive-{file_id[:8]}"
            if not base_nome.lower().endswith(extensao):
                base_nome = f"{PurePath(base_nome).stem}{extensao}"

            agora = self._relogio()
            self._registro.registrar_evidencia(protocolo, Evidencia(
                evidencia_id, base_nome, mime_detectado, total, str(destino), ator.id, agora
            ), ator)
            return EvidenciaDTO(
                id=evidencia_id, protocolo=protocolo, nome_arquivo=base_nome,
                content_type=mime_detectado, tamanho_bytes=total, enviado_em=agora
            )
        except httpx.HTTPError as exc:
            if await aiofiles.os.path.exists(temp_destino):
                await aiofiles.os.remove(temp_destino)
            if destino and await aiofiles.os.path.exists(destino):
                await aiofiles.os.remove(destino)
            raise ArquivoInvalido("Falha ao baixar o arquivo do Google Drive.") from exc
        except BaseException:
            if await aiofiles.os.path.exists(temp_destino):
                await aiofiles.os.remove(temp_destino)
            if destino and await aiofiles.os.path.exists(destino):
                await aiofiles.os.remove(destino)
            raise

    def obter_arquivo(
        self, protocolo: str, evidencia_id: str, ator: UsuarioAutenticado
    ) -> ArquivoEvidencia:
        ev = self._registro.obter_evidencia(protocolo, evidencia_id, ator)
        caminho = Path(ev.caminho).resolve()
        raiz = self._diretorio.resolve()
        # Defesa contra path traversal: garante que o arquivo está dentro do diretório de uploads.
        if not caminho.is_relative_to(raiz) or not caminho.is_file():
            raise RecursoNaoEncontrado("Arquivo da evidência não encontrado.")
        return ArquivoEvidencia(
            caminho=caminho, nome_arquivo=ev.nome_arquivo, content_type=ev.content_type
        )
