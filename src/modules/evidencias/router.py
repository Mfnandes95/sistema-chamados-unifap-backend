from typing import Annotated

from fastapi import APIRouter, File, Path, UploadFile, status
from fastapi.responses import FileResponse, Response

from src.core.container import ContainerDep
from src.modules.autenticacao.dependencies import UsuarioAtivo, UsuarioAtual
from src.modules.chamados.schemas import PROTOCOLO_REGEX
from src.modules.evidencias.interfaces import EvidenciaDTO, ImportarDriveRequest

router = APIRouter(prefix="/api/v1/chamados", tags=["evidências"])

ProtocoloPath = Annotated[str, Path(pattern=PROTOCOLO_REGEX)]


@router.post("/{protocolo}/evidencias", response_model=EvidenciaDTO,
             status_code=status.HTTP_201_CREATED)
async def enviar_evidencia(
    protocolo: ProtocoloPath,
    arquivo: Annotated[UploadFile, File(description="Imagem (.jpg/.png/.webp) ou vídeo .mp4")],
    ator: UsuarioAtivo,
    c: ContainerDep,
) -> EvidenciaDTO:
    return await c.evidencias.anexar(
        protocolo, arquivo.filename or "", arquivo.content_type or "", arquivo.read, ator)


@router.post("/{protocolo}/evidencias/google-drive", response_model=EvidenciaDTO,
             status_code=status.HTTP_201_CREATED)
async def importar_google_drive(
    protocolo: ProtocoloPath,
    dados: ImportarDriveRequest,
    ator: UsuarioAtivo,
    c: ContainerDep,
) -> EvidenciaDTO:
    return await c.evidencias.anexar_google_drive(
        protocolo, dados.url, dados.nome_arquivo, ator
    )


@router.get("/{protocolo}/evidencias/{evidencia_id}", response_model=None)
def baixar_evidencia(
    protocolo: ProtocoloPath,
    evidencia_id: str,
    ator: UsuarioAtual,
    c: ContainerDep,
) -> Response:
    arq = c.evidencias.obter_arquivo(protocolo, evidencia_id, ator)
    if arq.conteudo is not None:
        return Response(
            content=arq.conteudo,
            media_type=arq.content_type,
            headers={"Content-Disposition": f'inline; filename="{arq.nome_arquivo}"'},
        )
    assert arq.caminho is not None
    return FileResponse(
        path=arq.caminho,
        media_type=arq.content_type,
        filename=arq.nome_arquivo,
    )
