"""
Ponto de entrada do serviço FastAPI.

Camadas:
    api/routes/   → rotas HTTP (entrada/saída)
    core/         → montagem de prompt e orquestração (S1-A04+)
    providers/    → integração com LLM (Strategy Pattern)
    schemas/      → contratos Pydantic (S1-A02+)
"""

import logging
import math

import uvicorn
from fastapi import FastAPI

from fastapi.responses import JSONResponse
from app.api.routes.health import router as health_router
from app.api.routes.interpretador import router as interpretador_router
from app.api.routes.v2 import router as v2_router
from app.core.config import settings
from app.core.exceptions import LLMBaseException, LLMRateLimitError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gestão de Regras de Negócio — Serviço IA",
    description=(
        "Serviço Python responsável por interpretar regras de negócio "
        "em linguagem natural e devolver estruturas executáveis ao Spring."
    ),
    version="0.1.0",
)


@app.exception_handler(LLMBaseException)
async def llm_exception_handler(request, exc: LLMBaseException):
    logger.warning(
        "Falha de LLM propagada: %s - %s (%s %s)",
        exc.error_code,
        exc.message,
        request.method,
        request.url.path,
    )
    headers = None
    if isinstance(exc, LLMRateLimitError) and exc.retry_after_seconds is not None:
        headers = {"Retry-After": str(math.ceil(exc.retry_after_seconds))}
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "detail": exc.message,
            "error_code": exc.error_code,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """
    Rede de segurança para qualquer exceção não prevista (bug, não falha de LLM).
    Mantém o mesmo formato de resposta documentado no contrato com o Spring,
    sem vazar detalhes internos (stack trace, mensagem da exceção original).
    """
    logger.exception(
        "Erro inesperado ao processar %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Erro interno inesperado no serviço de IA.",
            "error_code": "INTERNAL_ERROR",
        },
    )


# --- Routers ---
app.include_router(health_router)
app.include_router(interpretador_router)
app.include_router(v2_router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )
