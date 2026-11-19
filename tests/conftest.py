from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings
from src.core.container import Container
from src.main import criar_app, montar_container
from src.modules.autenticacao.service import SENHA_PADRAO_SEED

MATRICULAS = {
    "solicitante": "20230001",
    "inativo": "20190002",
    "solicitante2": "20230003",
    "executor": "30000001",
    "executor2": "30000002",
    "gestor": "40000001",
}

CHAMADO_VALIDO = {
    "titulo": "Ar-condicionado parado",
    "descricao": "O ar-condicionado do laboratório não liga desde ontem.",
    "local_id": "BL1-1-LAB1",
    "categoria_id": "CLIMATIZACAO",
    "equipamento": "AR_CONDICIONADO",
    "impacta_aulas": True,
    "pessoas_afetadas": 40,
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024 * 64,
        supabase_url=None,
        supabase_secret_key=None,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    instancia, _ = montar_container(settings)
    return instancia


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    return criar_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def tokens(client: AsyncClient) -> dict[str, dict[str, str]]:
    headers: dict[str, dict[str, str]] = {}
    for papel, matricula in MATRICULAS.items():
        r = await client.post("/api/v1/auth/login",
                              json={"matricula": matricula, "senha": SENHA_PADRAO_SEED})
        assert r.status_code == 200, r.text
        headers[papel] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers
