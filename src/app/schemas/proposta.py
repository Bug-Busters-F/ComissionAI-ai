"""
Schemas Pydantic da API v2 (Sprint 2): lista de propostas, reinterpretação,
atualização de artefatos e simulação (IA-1, BUG-52).

Mantém o estilo do v1 (`regra.py`): valores de negócio em camelCase, taxa como
Decimal com 0 < taxa <= 1. A IA nunca devolve `status`, `id` persistido, ativação,
versão publicada nem identificadores financeiros.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CodigoPendencia(str, Enum):
    """Catálogo fechado de pendências."""

    CAMPO_AUSENTE = "CAMPO_AUSENTE"
    AMBIGUIDADE_CARGO = "AMBIGUIDADE_CARGO"
    AMBIGUIDADE_PUBLICO = "AMBIGUIDADE_PUBLICO"
    CADASTRO_INEXISTENTE = "CADASTRO_INEXISTENTE"
    MATRICULA_INVALIDA = "MATRICULA_INVALIDA"
    CRITERIO_NAO_SUPORTADO = "CRITERIO_NAO_SUPORTADO"
    TRECHO_INCOMPLETO = "TRECHO_INCOMPLETO"
    VIGENCIA_INCOMPATIVEL = "VIGENCIA_INCOMPATIVEL"
    BASE_AUSENTE = "BASE_AUSENTE"
    CONFLITO_REGRA = "CONFLITO_REGRA"
    TOOL_FALHA = "TOOL_FALHA"
    LIMITE_AGENTE_ATINGIDO = "LIMITE_AGENTE_ATINGIDO"
    TAXA_INVALIDA = "TAXA_INVALIDA"
    SIMULACAO_NAO_VALIDADA = "SIMULACAO_NAO_VALIDADA"
    NAO_SUPORTADO_NA_APURACAO = "NAO_SUPORTADO_NA_APURACAO"


class Pendencia(BaseModel):
    codigo: CodigoPendencia
    mensagem: str
    campo: str | None = None
    pergunta: str | None = None


class ContextoProposta(BaseModel):
    """Identifica de onde vem o pedido. Todos os ids são opacos para a IA."""

    campanhaId: str | None = None
    revisao: int | None = None
    origem: Literal["NOVA", "VERSAO_EXISTENTE"] = "NOVA"
    substituiVersao: str | None = None

    model_config = ConfigDict(extra="ignore")


class VigenciaCampanha(BaseModel):
    inicio: date | None = None
    fim: date | None = None

    @model_validator(mode="after")
    def _validar(self) -> "VigenciaCampanha":
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ValueError("A vigência da campanha tem fim anterior ao início.")
        return self


class Origem(BaseModel):
    """Trecho literal do pedido que originou um bloco."""

    trecho: str
    inicio: int | None = None
    fim: int | None = None


class FaixaValor(BaseModel):
    campo: Literal["VENDA"] = "VENDA"
    min: Decimal | None = None
    max: Decimal | None = None
    minInclusivo: bool = True
    maxInclusivo: bool = False

    @model_validator(mode="after")
    def _validar(self) -> "FaixaValor":
        if self.min is None and self.max is None:
            raise ValueError("Faixa de valor sem limites.")
        if self.min is not None and self.min < 0:
            raise ValueError("O limite mínimo da faixa não pode ser negativo.")
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError("A faixa tem máximo menor que o mínimo.")
        return self


class Condicoes(BaseModel):
    canal: str | None = None
    codMarca: int | None = None
    descrMarca: str | None = None
    codCargo: int | None = None
    descriCargo: str | None = None
    codLoja: int | None = None
    matricula: str | None = None
    faixaValor: FaixaValor | None = None


TipoOperacao = Literal[
    "TAXA_ABSOLUTA",
    "ADICIONAR_PP",
    "REDUZIR_PP",
    "AUMENTAR_PERCENTUAL",
    "REDUZIR_PERCENTUAL",
]


class Operacao(BaseModel):
    """O que fazer com a taxa. IA-2 só preenche TAXA_ABSOLUTA; os demais são do IA-5."""

    tipo: TipoOperacao
    valor: Decimal


class Bonus(BaseModel):
    """Adicional sobre a venda, em percentual e/ou valor fixo por venda."""

    percentual: Decimal | None = None
    valorFixo: Decimal | None = None

    @model_validator(mode="after")
    def _validar(self) -> "Bonus":
        if self.percentual is None and self.valorFixo is None:
            raise ValueError("Bônus sem percentual nem valor fixo.")
        if self.percentual is not None and not (Decimal("0") < self.percentual <= Decimal("1")):
            raise ValueError("O bônus percentual deve estar entre 0 (exclusivo) e 1.")
        if self.valorFixo is not None and self.valorFixo <= 0:
            raise ValueError("O bônus de valor fixo deve ser positivo.")
        return self


class ReferenciaBase(BaseModel):
    fonte: Literal["BASE_COMISS", "TB_REGRA", "CADASTRO"]
    chave: dict[str, Any] = Field(default_factory=dict)
    taxaBase: Decimal | None = None
    consultadaEm: datetime | None = None


class EvidenciaTool(BaseModel):
    """Registro rastreável de uma consulta/execução do agente."""

    ferramenta: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    status: Literal["OK", "SEM_DADOS", "AMBIGUO", "FALHA"]
    resumo: str = ""
    duracaoMs: int = 0
    passo: int = 0
    blocosAfetados: list[str] = Field(default_factory=list)


class BlocoProposta(BaseModel):
    idLocal: str
    condicoes: Condicoes = Field(default_factory=Condicoes)
    operacao: Operacao | None = None
    taxa: Decimal | None = None
    bonus: Bonus | None = None
    dataInicio: date | None = None
    dataFim: date | None = None
    origem: Origem | None = None
    referencias: list[ReferenciaBase] = Field(default_factory=list)
    evidencias: list[EvidenciaTool] = Field(default_factory=list)
    explicacao: str | None = None  # IA-7 (Humberto)
    codigoPython: str | None = None  # IA-7 (Humberto)
    confianca: Decimal | None = None
    pendencias: list[Pendencia] = Field(default_factory=list)

    @field_validator("taxa")
    @classmethod
    def _validar_taxa(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (value <= Decimal("0") or value > Decimal("1.0000")):
            raise ValueError(
                f"A taxa deve ser maior que 0 e menor ou igual a 1.0000 (100%). Valor recebido: {value}"
            )
        return value

    @field_validator("confianca")
    @classmethod
    def _validar_confianca(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (value < 0 or value > 1):
            raise ValueError("A confiança deve estar entre 0 e 1.")
        return value

    @model_validator(mode="after")
    def _validar_vigencia(self) -> "BlocoProposta":
        if self.dataInicio and self.dataFim and self.dataFim < self.dataInicio:
            raise ValueError("A dataFim não pode ser anterior à dataInicio.")
        return self


class InterpretarRequestV2(BaseModel):
    texto: str = Field(..., min_length=1)
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    vigenciaCampanha: VigenciaCampanha | None = None
    dataReferencia: date | None = None
    competencia: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    catalogo: dict[str, Any] = Field(default_factory=dict)

    @field_validator("texto")
    @classmethod
    def _texto_nao_vazio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("O texto do comando não pode ser vazio ou conter apenas espaços.")
        return value

    model_config = ConfigDict(extra="ignore")


StatusInterpretacao = Literal["PROPOSTA_COMPLETA", "PROPOSTA_COM_PENDENCIAS", "SEM_PROPOSTA"]


class InterpretarResponseV2(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    propostas: list[BlocoProposta] = Field(default_factory=list)
    pendenciasGerais: list[Pendencia] = Field(default_factory=list)
    trechosNaoMapeados: list[Origem] = Field(default_factory=list)
    trilhaFerramentas: list[EvidenciaTool] = Field(default_factory=list)
    status: StatusInterpretacao = "SEM_PROPOSTA"


class ReinterpretarRequest(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    idLocal: str
    textoAlterado: str = Field(..., min_length=1)
    blocoAtual: BlocoProposta
    demaisBlocos: list[BlocoProposta] = Field(default_factory=list)
    vigenciaCampanha: VigenciaCampanha | None = None
    dataReferencia: date | None = None
    catalogo: dict[str, Any] = Field(default_factory=dict)


class ReinterpretarResponse(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    propostasSubstituicao: list[BlocoProposta] = Field(default_factory=list)
    camposAlterados: list[str] = Field(default_factory=list)
    pendenciasGerais: list[Pendencia] = Field(default_factory=list)


class AtualizarArtefatosRequest(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    bloco: BlocoProposta
    camposEditados: list[str] = Field(default_factory=list)
    origemCampos: dict[str, Literal["MANUAL", "IA"]] = Field(default_factory=dict)


class AtualizarArtefatosResponse(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    bloco: BlocoProposta


# ---------------------------------------------------------------------------
# Simulação (requisito do cliente)
# ---------------------------------------------------------------------------


class Cenario(BaseModel):
    nome: str
    multiplicadorVendas: Decimal = Decimal("1")

    @field_validator("multiplicadorVendas")
    @classmethod
    def _positivo(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("O multiplicador de vendas deve ser positivo.")
        return value


class SimularRequest(BaseModel):
    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    propostas: list[BlocoProposta]
    competencia: str = Field(..., pattern=r"^\d{4}-\d{2}$")
    pedido: str | None = Field(
        default=None,
        description="Pedido livre do gestor (ex.: 'e se as vendas crescerem 20%?'). O agente monta os cenários.",
    )
    cenarios: list[Cenario] = Field(default_factory=list)
    filtro: dict[str, Any] = Field(default_factory=dict)


class ResultadoCenario(BaseModel):
    cenario: str
    totalVendas: Decimal
    totalComissao: Decimal
    porBloco: dict[str, Decimal] = Field(default_factory=dict)
    porMatricula: dict[str, Decimal] = Field(default_factory=dict)


class SimularResponse(BaseModel):
    origem: Literal["TEMPLATE", "CODIGO_LIVRE"]
    simulacao: Literal["SIMULACAO_SANDBOX"] = "SIMULACAO_SANDBOX"
    aviso: str = "Resultado de simulação. Não substitui a apuração oficial."
    resultados: list[ResultadoCenario] = Field(default_factory=list)
    observacoes: list[str] = Field(default_factory=list)
    codigoExecutado: str | None = None
    pendencias: list[Pendencia] = Field(default_factory=list)
    trilhaFerramentas: list[EvidenciaTool] = Field(default_factory=list)
