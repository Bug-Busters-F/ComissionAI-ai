"""
Rotas v2 (Sprint 2): interpretação com lista de propostas, reinterpretação e
atualização de artefatos após edição manual (IA-6/IA-7). O contrato é validado
e documentado no Swagger.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.agente import AgenteInterpretador
from app.core.agente.hooks import HooksAjusteSobreBase
from app.core.services.artefatos import ServicoArtefatos
from app.core.services.reinterpretador import ServicoReinterpretacao
from app.core.simulacao.servico import ServicoSimulacao
from app.providers import get_provider
from app.schemas.proposta import (
    AtualizarArtefatosRequest,
    AtualizarArtefatosResponse,
    GerarProgramaRequest,
    InterpretarRequestV2,
    InterpretarResponseV2,
    ProgramaArmazenado,
    ProgramaGeradoResponse,
    ReinterpretarRequest,
    ReinterpretarResponse,
    SimularRequest,
    SimularResponse,
)
from app.tools import criar_registry

router = APIRouter(prefix="/api/v2", tags=["v2"])

def get_agente() -> AgenteInterpretador:
    """Fábrica injetável (os testes substituem por um agente com LLM e backend falsos)."""
    return AgenteInterpretador(get_provider(), criar_registry(), hooks=HooksAjusteSobreBase())


def get_simulador() -> ServicoSimulacao:
    return ServicoSimulacao(get_provider(), criar_registry(incluir_simulacao=True))


@router.post(
    "/gerar-programa",
    summary="Gerar e validar o programa da simulação antes da revisão técnica (IA-2)",
    response_model=ProgramaGeradoResponse,
)
def gerar_programa(
    request: GerarProgramaRequest, servico: ServicoSimulacao = Depends(get_simulador)
) -> ProgramaGeradoResponse:
    """
    Gera (quando há cálculo adicional) e valida o código ANTES de simular sobre vendas reais, devolvendo
    uma assinatura que identifica a versão aprovada. `/simular` pode então executar exatamente esse código
    via `codigoAprovado`/`assinaturaPrograma`, sem reinventá-lo a cada clique em simular.
    """
    return servico.gerar_programa(request)


@router.get(
    "/programa/{assinatura}",
    summary="Recuperar o código de uma simulação pela assinatura, pra revisão posterior (IA-2)",
    response_model=ProgramaArmazenado,
)
def buscar_programa(
    assinatura: str, servico: ServicoSimulacao = Depends(get_simulador)
) -> ProgramaArmazenado:
    """
    Recupera o código (TEMPLATE fixo ou CODIGO_LIVRE já gerado por /gerar-programa ou /simular)
    pela assinatura sha256. O backend guarda só a assinatura como referência; o código em si
    fica persistido aqui, pra quem precisar reabrir e revisar depois.
    """
    programa = servico.buscar_programa(assinatura)
    if programa is None:
        raise HTTPException(status_code=404, detail="Nenhum programa encontrado para essa assinatura.")
    return programa


@router.post(
    "/simular",
    summary="Simular as propostas executando código gerado em sandbox",
    response_model=SimularResponse,
)
def simular(request: SimularRequest, servico: ServicoSimulacao = Depends(get_simulador)) -> SimularResponse:
    """
    Resultado de SIMULAÇÃO (nunca apuração oficial). Casos genéricos usam modelo fixo; casos complexos usam
    código gerado pela IA, executado em sandbox e devolvido junto com o resultado para auditoria.
    Aceita `vendas` (recorte já resolvido pelo backend, BACK-10) como única fonte de dados quando informado,
    e `codigoAprovado`/`assinaturaPrograma` (de /gerar-programa, IA-2) para executar sem regerar o código.
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


def get_reinterpretador(agente: AgenteInterpretador = Depends(get_agente)) -> ServicoReinterpretacao:
    """Reinterpretação usa o mesmo agente (e hooks) da interpretação inicial."""
    return ServicoReinterpretacao(agente)


def get_artefatos() -> ServicoArtefatos:
    """Atualização de artefatos é determinística: não usa LLM nem ferramentas."""
    return ServicoArtefatos()


@router.post(
    "/reinterpretar",
    summary="Reinterpretar o texto alterado de uma regra (IA-6)",
    response_model=ReinterpretarResponse,
)
def reinterpretar(
    request: ReinterpretarRequest,
    servico: ServicoReinterpretacao = Depends(get_reinterpretador),
) -> ReinterpretarResponse:
    return servico.reinterpretar(request)


@router.post(
    "/atualizar-artefatos",
    summary="Atualizar explicação e código após edição manual (IA-6/IA-7)",
    response_model=AtualizarArtefatosResponse,
)
def atualizar_artefatos(
    request: AtualizarArtefatosRequest,
    servico: ServicoArtefatos = Depends(get_artefatos),
) -> AtualizarArtefatosResponse:
    return servico.atualizar(request)
