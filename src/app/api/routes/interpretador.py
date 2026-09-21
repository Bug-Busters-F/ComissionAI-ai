"""
Rota de interpretação de regras em linguagem natural (Task S1-A08).

Recebe texto + contexto do Spring, executa o pipeline de interpretação
(prompt → LLM → normalização → validação) e devolve a proposta estruturada
com pendências, sem persistir nem ativar regras.
"""

from fastapi import APIRouter

from app.core.services.interpretador import InterpretadorRegraService
from app.schemas.regra import InterpretacaoRegraRequest, InterpretacaoRegraResponse

router = APIRouter(tags=["interpretador"])


@router.post(
    "/api/v1/interpretar",
    summary="Interpretar regra em linguagem natural",
    response_model=InterpretacaoRegraResponse,
)
def interpretar(request: InterpretacaoRegraRequest) -> InterpretacaoRegraResponse:
    """Executa o pipeline de interpretação e devolve a proposta estruturada."""
    service = InterpretadorRegraService()
    return service.interpretar(request)
