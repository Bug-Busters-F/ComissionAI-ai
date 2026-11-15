"""
Contrato de `POST /api/v2/executar-programa` (IA-10 / BUG-123), no formato que o backend já envia
(`AiServiceClient.executarProgramaPython`, BACK-9/BACK-11): o programa aprovado (`calcular_comissao`) é
executado no sandbox uma vez por item; a consolidação dos cenários e da apuração fica no backend.

Campos extras são ignorados, para o backend poder evoluir o payload sem quebrar a IA.
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MOTOR = "PYTHON_SANDBOX"


class ContextoExecucao(BaseModel):
    """Identificadores do backend; a IA só registra e devolve (não autentica usuários)."""

    modo: str | None = Field(default=None, description="SIMULACAO ou APURACAO.")
    campanhaId: int | str | None = None
    versaoCampanha: int | None = None
    versaoProgramaPython: int | str | None = None
    competencia: str | None = None
    dataInicio: str | None = None
    dataFim: str | None = None
    execucaoId: str | None = None
    usuarioSolicitanteId: str | None = None

    model_config = ConfigDict(extra="allow")


class ItemExecucao(BaseModel):
    id: str = Field(min_length=1, description="Id opaco do item (ex.: `<idVenda>#100`); volta em `resultados`.")
    venda: dict[str, Any] = Field(description="Venda como `CampanhaProgramaPythonService.montarVendaParaPython`.")
    contexto: dict[str, Any] | None = Field(default=None, description="Ex.: cenário e fator; 2º argumento opcional.")

    model_config = ConfigDict(extra="ignore")


class ExecutarProgramaRequest(BaseModel):
    codigoFonte: str = Field(min_length=1)
    contexto: ContextoExecucao = Field(default_factory=ContextoExecucao)
    itens: list[ItemExecucao] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("itens")
    @classmethod
    def _ids_unicos(cls, itens: list[ItemExecucao]) -> list[ItemExecucao]:
        vistos: set[str] = set()
        for item in itens:
            if item.id in vistos:
                raise ValueError(f"id de item repetido: {item.id}")
            vistos.add(item.id)
        return itens


class ResultadoItem(BaseModel):
    id: str
    aplicada: bool = Field(description="false = o programa devolveu None (nenhuma regra aplicada).")
    comissao: Decimal | None = Field(default=None, description="Escala 2, HALF_UP; null quando não aplicada.")


class ExecutarProgramaResponse(BaseModel):
    sucesso: bool
    motor: str = MOTOR
    totalItens: int = 0
    resultados: list[ResultadoItem] | None = None
    erro: str | None = Field(default=None, description="Tipo da falha: VALIDACAO, TIMEOUT, ERRO_CODIGO etc.")
    detalhe: str | None = None
    violacoes: list[str] = Field(default_factory=list)
    assinaturaPrograma: str | None = Field(
        default=None, description="sha256 do código executado (mesmo cálculo do checksum do BACK-9)."
    )
    contexto: ContextoExecucao | None = None


class ExecutarProgramaErro(ExecutarProgramaResponse):
    """Corpo das respostas 422 da rota: o formato acima mais `detail`/`error_code` do catálogo (IA-10)."""

    sucesso: Literal[False] = False
    detail: str
    error_code: str
