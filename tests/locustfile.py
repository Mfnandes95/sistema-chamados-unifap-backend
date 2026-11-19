"""Teste de carga: `locust -f tests/locustfile.py --host http://localhost:8000`."""

from locust import HttpUser, between, task

from src.modules.autenticacao.service import SENHA_PADRAO_SEED
from tests.conftest import CHAMADO_VALIDO


class Solicitante(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        r = self.client.post("/api/v1/auth/login",
                             json={"matricula": "20230001", "senha": SENHA_PADRAO_SEED})
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    @task(3)
    def listar(self) -> None:
        self.client.get("/api/v1/chamados")

    @task(1)
    def abrir(self) -> None:
        self.client.post("/api/v1/chamados", json=CHAMADO_VALIDO)
