"""
Rotas v2 (Sprint 2): interpretação com lista de propostas, reinterpretação e
atualização de artefatos. As duas últimas são STUBS (501) até o IA-6 (Humberto)
implementar o corpo; o contrato já é validado e documentado no Swagger.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.agente import AgenteInterpretador
from app.core.simulacao.servico import ServicoSimulacao
from app.providers import get_provider
from app.schemas.proposta import (
    AtualizarArtefatosRequest,
    AtualizarArtefatosResponse,
    InterpretarRequestV2,
    InterpretarResponseV2,
    ReinterpretarRequest,
    ReinterpretarResponse,
    SimularRequest,
    SimularResponse,
)
from app.tools import criar_registry

router = APIRouter(prefix="/api/v2", tags=["v2"])

_NAO_IMPLEMENTADO = {
    501: {
        "description": "Operação ainda não implementada (IA-6).",
        "content": {"application/json": {"example": {"detail": "...", "error_code": "NAO_IMPLEMENTADO"}}},
    }
}


def get_agente() -> AgenteInterpretador:
    """Fábrica injetável (os testes substituem por um agente com LLM e backend falsos)."""
    return AgenteInterpretador(get_provider(), criar_registry())


def get_simulador() -> ServicoSimulacao:
    return ServicoSimulacao(get_provider(), criar_registry(incluir_simulacao=True))


@router.post(
    "/simular",
    summary="Simular as propostas executando código gerado em sandbox",
    response_model=SimularResponse,
)
def simular(request: SimularRequest, servico: ServicoSimulacao = Depends(get_simulador)) -> SimularResponse:
    """
    Resultado de SIMULAÇÃO (nunca apuração oficial). Casos genéricos usam modelo fixo; casos complexos usam
    código gerado pela IA, executado em sandbox e devolvido junto com o resultado para auditoria.
    """
    return servico.simular(request)


@router.post(
    "/interpretar",
    summary="Interpretar campanha em linguagem natural (lista de propostas)",
    response_model=InterpretarResponseV2,
)
def interpretar(
    request: InterpretarRequestV2, agente: AgenteInterpretador = Depends(get_agente)
) -> InterpretarResponseV2:
    """Extrai uma ou mais regras, consulta cadastros/bases/concorrência e devolve propostas com pendências."""
    return agente.executar(request)


@router.post(
    "/reinterpretar",
    summary="Reinterpretar o texto alterado de uma regra (IA-6, stub)",
    response_model=ReinterpretarResponse,
    responses=_NAO_IMPLEMENTADO,
)
def reinterpretar(request: ReinterpretarRequest):
    return JSONResponse(
        status_code=501,
        content={"detail": "Reinterpretação localizada ainda não implementada (IA-6).", "error_code": "NAO_IMPLEMENTADO"},
    )


@router.post(
    "/atualizar-artefatos",
    summary="Atualizar explicação e código após edição manual (IA-6/IA-7, stub)",
    response_model=AtualizarArtefatosResponse,
    responses=_NAO_IMPLEMENTADO,
)
def atualizar_artefatos(request: AtualizarArtefatosRequest):
    return JSONResponse(
        status_code=501,
        content={"detail": "Atualização de artefatos ainda não implementada (IA-6/IA-7).", "error_code": "NAO_IMPLEMENTADO"},
    )
