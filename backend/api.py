"""
backend/api.py — Rotas da API REST do Hub de Automações.
"""

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

router = APIRouter()

_DB_CONTRATACOES = Path("database/contratacoes.json")

_VAZIO = json.dumps(
    {"ultima_atualizacao": None, "total": 0, "chamados": []},
    ensure_ascii=False,
)


@router.get("/contratacoes", summary="Chamados de contratação ativos")
async def get_contratacoes() -> Response:
    """
    Retorna o snapshot mais recente dos chamados de contratação do GLPI.
    O arquivo é atualizado pelo worker `automations/contratacoes/glpi_sync.py`.
    """
    if not _DB_CONTRATACOES.exists():
        return Response(content=_VAZIO, media_type="application/json")
    try:
        # Serve o JSON diretamente sem re-parsear (evita overhead desnecessário)
        return Response(
            content=_DB_CONTRATACOES.read_text(encoding="utf-8"),
            media_type="application/json",
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"erro": str(exc), "total": 0, "chamados": []},
        )
