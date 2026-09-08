"""
Rota de health check — confirma que o serviço está no ar.

Usada pelo Spring e pela infra para verificar disponibilidade
antes de enviar requisições de interpretação.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health() -> dict:
    """Retorna status do serviço."""
    return {"status": "ok"}
