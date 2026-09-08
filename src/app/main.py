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

from app.api.routes.health import router as health_router
from app.core.config import settings

app = FastAPI(
    title="Gestão de Regras de Negócio — Serviço IA",
    description=(
        "Serviço Python responsável por interpretar regras de negócio "
        "em linguagem natural e devolver estruturas executáveis ao Spring."
    ),
    version="0.1.0",
)

# --- Routers ---
app.include_router(health_router)

# S1-A08: adicionar router de interpretação aqui.


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload,
    )
