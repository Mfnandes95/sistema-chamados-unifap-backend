from typing import Annotated

from fastapi import APIRouter, File, Path, UploadFile, status

from src.core.container import ContainerDep
from src.modules.autenticacao.dependencies import UsuarioAtivo
from src.modules.chamados.schemas import PROTOCOLO_REGEX
from src.modules.evidencias.interfaces import EvidenciaDTO

router = APIRouter(prefix="/api/v1/chamados", tags=["evidências"])


@router.post("/{protocolo}/evidencias", response_model=EvidenciaDTO,
             status_code=status.HTTP_201_CREATED)
async def enviar_evidencia(
    protocolo: Annotated[str, Path(pattern=PROTOCOLO_REGEX)],
    arquivo: Annotated[UploadFile, File(description="Imagem (.jpg/.png/.webp) ou vídeo .mp4")],
    ator: UsuarioAtivo,
    c: ContainerDep,
) -> EvidenciaDTO:
    return await c.evidencias.anexar(
        protocolo, arquivo.filename or "", arquivo.content_type or "", arquivo.read, ator)
