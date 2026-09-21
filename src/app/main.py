"""
Ponto de entrada do serviço FastAPI.

Camadas:
    api/routes/   → rotas HTTP (entrada/saída)
    core/         → montagem de prompt e orquestração (S1-A04+)
    providers/    → integração com LLM (Strategy Pattern)
    schemas/      → contratos Pydantic (S1-A02+)
"""

import uvicorn
from fastapi import FastAPI

from fastapi.responses import JSONResponse
from app.api.routes.health import router as health_router
from app.api.routes.interpretador import router as interpretador_router
from app.core.config import settings
from app.core.exceptions import LLMBaseException

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
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "error_code": exc.error_code,
        },
    )


# --- Routers ---
app.include_router(health_router)
app.include_router(interpretador_router)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )
