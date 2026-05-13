"""
main.py — Hub de Automações: servidor web FastAPI.

Rotas:
    GET /                    → Dashboard (frontend/index.html)
    GET /api/contratacoes    → Snapshot JSON dos chamados ativos do GLPI
    GET /docs                → Swagger UI (automático pelo FastAPI)

Como rodar:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse

from backend.api import router

_BASE = "/hub/automacoes"

app = FastAPI(
    title="Hub de Automações",
    description="Dashboard centralizado de automações internas.",
    version="1.0.0",
    root_path=_BASE,
)

app.include_router(router, prefix=f"{_BASE}/api")


@app.get(_BASE, include_in_schema=False)
@app.get(f"{_BASE}/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse("frontend/index.html")
