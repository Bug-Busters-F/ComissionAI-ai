"""
Contrato de `POST /api/v2/anomalias/analisar` (IA-8 / BUG-121; consumidor: BACK-12 e FRONT-6).

A entrada aceita o mesmo formato de `vendas` e `dadosRh` do recorte do backend (BACK-10,
`RecortePopulacaoIaResponse`); campos extras são ignorados.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.schemas.proposta import ContextoProposta


class VendaAnomalia(BaseModel):
    id: str
    matricula: str | None = None
    codLoja: int | None = None
    codMarca: int | None = None
    codCargo: int | None = Field(default=None, description="Cargo do RH; se ausente, vem de `dadosRh`.")
    descriCargo: str | None = None
    valorVenda: Decimal
    dataVenda: date

    model_config = ConfigDict(extra="ignore")


class ColaboradorRh(BaseModel):
    matricula: str
    codLoja: int | None = None
    codCargo: int | None = None
    descriCargo: str | None = None

    model_config = ConfigDict(extra="ignore")


class ParametrosAnomalia(BaseModel):
    """Ausentes = padrões do serviço (`ANOMALIA_K`, `ANOMALIA_AMOSTRA_MINIMA`); os efetivos voltam em `metodo`."""

    k: Decimal | None = Field(default=None, gt=0, le=10, description="Multiplicador do IQR (Tukey: 1,5).")
    amostraMinima: int | None = Field(default=None, ge=4, le=1000,
                                      description="Observações mínimas (colaborador/dia) para avaliar um grupo.")


class AnalisarAnomaliasRequest(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    competencia: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    vendas: list[VendaAnomalia]
    dadosRh: list[ColaboradorRh] = Field(
        default_factory=list,
        description="RH da competência. Quando informado, é a referência: venda de matrícula ausente é erro de carga.",
    )
    parametros: ParametrosAnomalia = Field(default_factory=ParametrosAnomalia)
    versaoFontes: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("versaoFontes", "versoesFontes"),
        description="Hashes do recorte (BACK-10, `versoesFontes`), ecoados.",
    )


# ------------------------------------------------------------------------------ saída
class GrupoComparavel(BaseModel):
    """Marca + código do cargo + descrição do cargo (150 = GERENTE DE LOJA ou GERENTE QUIOSQUE) + competência."""

    codMarca: int
    codCargo: int
    descriCargo: str | None = None
    competencia: str


class FaixaEsperada(BaseModel):
    min: Decimal
    max: Decimal


class EvidenciaIqr(BaseModel):
    q1: Decimal
    mediana: Decimal
    q3: Decimal
    iqr: Decimal


class MetodoAnomalia(BaseModel):
    nome: Literal["IQR_TUKEY"] = "IQR_TUKEY"
    k: Decimal
    amostraMinima: int
    quartis: Literal["INTERPOLACAO_LINEAR_INCLUSIVA"] = "INTERPOLACAO_LINEAR_INCLUSIVA"
    unidade: Literal["TOTAL_COLABORADOR_DIA"] = "TOTAL_COLABORADOR_DIA"
    arredondamento: str = ("Quartis e limites em centavos (HALF_UP); faixa = [Q1 − k·IQR, Q3 + k·IQR], com mínimo "
                           "0 quando o grupo não tem valores negativos.")


class AlertaAnomalia(BaseModel):
    id: str = Field(description="Identificador de negócio estável (competência + grupo + matrícula + dia): não muda "
                    "quando outras vendas da base mudam; a versão dos dados está em `versaoDados`.")
    tipo: Literal["ACIMA_DA_FAIXA", "ABAIXO_DA_FAIXA"]
    matricula: str
    data: date
    valorObservado: Decimal = Field(description="Total vendido pelo colaborador no dia.")
    qtdVendas: int
    vendaIds: list[str] = Field(default_factory=list, description="Até 50 vendas do dia, para conferência.")
    faixaEsperada: FaixaEsperada
    distanciaFaixa: Decimal = Field(description="Quanto o valor passa do limite da faixa (sempre positivo).")
    grupo: GrupoComparavel
    tamanhoAmostra: int
    evidencia: EvidenciaIqr
    explicacao: str


class ResultadoGrupo(BaseModel):
    grupo: GrupoComparavel
    status: Literal["ANALISADO", "AMOSTRA_INSUFICIENTE", "SEM_VARIACAO"]
    tamanhoAmostra: int = Field(description="Observações colaborador/dia do grupo.")
    colaboradores: int
    evidencia: EvidenciaIqr | None = None
    faixaEsperada: FaixaEsperada | None = None
    qtdAlertas: int = 0
    motivo: str | None = None


class ErroCarga(BaseModel):
    """Vendas fora da análise, sempre explícitas (nunca entram como zero nem geram alerta)."""

    codigo: Literal["VENDA_SEM_RH", "VENDA_SEM_MARCA", "FORA_DA_COMPETENCIA"]
    motivo: str
    quantidade: int
    valorVendas: Decimal
    matriculas: list[str] = Field(default_factory=list, description="Até 50.")
    vendaIds: list[str] = Field(default_factory=list, description="Até 50.")


class CoberturaDias(BaseModel):
    diasNaCompetencia: int
    diasComVenda: list[date]
    diasSemCobertura: int = Field(description="Dias da competência sem nenhuma venda no recorte (não viram zero).")


class ResumoAnomalias(BaseModel):
    totalVendas: int
    vendasAnalisadas: int
    observacoes: int
    grupos: int
    gruposAnalisados: int
    gruposAmostraInsuficiente: int
    gruposSemVariacao: int
    alertas: int
    vendasComErroCarga: int


class AnalisarAnomaliasResponse(BaseModel):
    tipo: Literal["INDICIO_PARA_CONFERENCIA"] = "INDICIO_PARA_CONFERENCIA"
    aviso: str = "Anomalia é indício para conferência, não correção automática da venda."
    execucaoId: str | None = None
    contexto: ContextoProposta | None = Field(default=None, description="Identificadores recebidos, devolvidos (IA-10).")
    competencia: str
    granularidade: Literal["DIARIA"] = "DIARIA"
    metodo: MetodoAnomalia
    versaoDados: str = Field(description="sha256 do recorte analisado + parâmetros (independe da ordem).")
    versaoFontes: dict[str, Any] = Field(default_factory=dict)
    resumo: ResumoAnomalias
    alertas: list[AlertaAnomalia] = Field(default_factory=list)
    grupos: list[ResultadoGrupo] = Field(default_factory=list)
    errosCarga: list[ErroCarga] = Field(default_factory=list)
    cobertura: CoberturaDias
    observacoes: list[str] = Field(default_factory=list)
    explicacao: str
