# Sistema de Chamados para Infraestrutura Universitária (UNIFAP) — Backend

Motor de backend em **Monólito Modular** com **FastAPI (ASGI)**, **Python 3.12+**, **Pydantic v2** e tipagem estrita (`mypy --strict`).

Os módulos se comunicam exclusivamente via `typing.Protocol` e DTOs imutáveis, utilizando adaptadores em memória (`InMemoryRepository`, `InMemoryCatalogoAdapter`, `InMemoryAuthAdapter`) para validação completa antes da integração com o banco físico.

## Stack
- **API & ASGI:** FastAPI + Uvicorn
- **Validação & Config:** Pydantic v2 + `pydantic-settings`
- **Segurança & RBAC:** PyJWT + `pwdlib[argon2]` (`SOLICITANTE`, `EXECUTOR`, `GESTOR`)
- **Uploads & Assíncrono:** `python-multipart`, `aiofiles`, `BackgroundTasks`
- **Qualidade & Testes:** `pytest`, `pytest-asyncio`, `httpx`, `pytest-benchmark`, `locust`, `mypy --strict`

## Como executar
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn src.main:app --reload
```

- Raiz: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Healthcheck: `http://127.0.0.1:8000/health`

## Testes e tipagem
```bash
.venv/bin/pytest -q
.venv/bin/mypy src tests
```

## Usuários seed (ambiente de desenvolvimento)
Senha padrão para todos: `Unifap@2026`

| Matrícula | Perfil | Vínculo |
|---|---|---|
| `20230001` | `SOLICITANTE` | ativo |
| `20190002` | `SOLICITANTE` | inativo |
| `30000001` | `EXECUTOR` (Elétrica) | ativo |
| `30000002` | `EXECUTOR` (TI) | ativo |
| `40000001` | `GESTOR` | ativo |
