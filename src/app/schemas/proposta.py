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

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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
    execucaoId: str | None = Field(
        default=None, description="Id da execução no backend; devolvido em cada explicação (IA-7)."
    )
    # IA-10: rastreabilidade ponta a ponta. A IA não autentica usuários: só registra e devolve o id recebido.
    usuarioSolicitanteId: str | None = None
    versaoPrograma: str | None = Field(
        default=None, description="Versão do programa aprovada no backend (BACK-9); a IA devolve também a assinatura."
    )

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


class VendaRecorte(BaseModel):
    """Uma venda do recorte enviado pelo backend (BACK-10). Mesmo formato de `ESQUEMA_DADOS['vendas']`."""

    id: str
    matricula: str | None = None
    codLoja: int | None = None
    codMarca: int | None = None
    codCargo: int | None = None
    descriCargo: str | None = Field(
        default=None,
        description="Descrição do cargo no RH. Distingue cargos com o mesmo código e taxas diferentes "
        "(ex.: 150 = GERENTE DE LOJA ou GERENTE QUIOSQUE) ao resolver a taxa contratual.",
    )
    valorVenda: Decimal
    dataVenda: date
    canal: str | None = None
    taxaContratual: Decimal | None = Field(
        default=None,
        description="Taxa contratual já resolvida pelo backend para esta venda (opcional). Quando ausente, "
        "é resolvida a partir de `taxasContratuais` da requisição.",
    )

    model_config = ConfigDict(extra="ignore")


class TaxaContratual(BaseModel):
    """Taxa do BASE_COMMISS por marca e cargo (BACK-10: `taxasContratuais`)."""

    codMarca: int
    codCargo: int
    descriCargo: str | None = None
    taxa: Decimal = Field(validation_alias=AliasChoices("taxa", "percentual"))

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    @field_validator("taxa")
    @classmethod
    def _taxa_valida(cls, value: Decimal) -> Decimal:
        if not (Decimal("0") <= value <= Decimal("1")):
            raise ValueError("A taxa contratual deve estar entre 0 e 1.")
        return value


class PeriodoCampanha(BaseModel):
    """Vigência da campanha usada na projeção do custo (dias inclusivos ÷ 30, como no backend)."""

    dataInicio: date
    dataFim: date

    @model_validator(mode="after")
    def _validar(self) -> "PeriodoCampanha":
        if self.dataFim < self.dataInicio:
            raise ValueError("A data final da campanha não pode ser anterior à inicial.")
        return self


class PendenciaAceita(BaseModel):
    """Pendência de base aceita com ressalva (BACK-7), listada como risco da simulação."""

    tipoBase: str | None = None
    competencia: str | None = None
    linha: int | None = None
    campo: str | None = None
    motivo: str | None = None
    aceitaPor: str | None = None
    motivoAceite: str | None = None

    model_config = ConfigDict(extra="ignore")


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
    vendas: list[VendaRecorte] | None = Field(
        default=None,
        description="Recorte de vendas já resolvido pelo backend (BACK-10). Quando informado, é a ÚNICA "
        "fonte de dados da simulação — a consulta interna ao backend (ferramenta obter_dados_simulacao) "
        "não é usada, para não buscar silenciosamente outra base.",
    )
    codigoAprovado: str | None = Field(
        default=None,
        description="Código já gerado e validado por /gerar-programa (IA-2). Quando informado, a simulação "
        "executa ESSE código sem regerá-lo — a geração não é reinventada a cada clique em simular.",
    )
    assinaturaPrograma: str | None = Field(
        default=None,
        description="Assinatura (sha256) de `codigoAprovado`, devolvida por /gerar-programa, para detectar "
        "divergência entre o que foi aprovado e o que está sendo executado.",
    )
    orcamento: Decimal | None = Field(
        default=None,
        description="Teto orçamentário confirmado da campanha (BACK-8). Comparado ao custo projetado de cada "
        "cenário; o cenário de 100% define o enquadramento para encaminhamento ao gerente.",
    )
    periodoCampanha: PeriodoCampanha | None = Field(
        default=None,
        description="Vigência da campanha para a projeção. Ausente: mês inteiro da competência (igual ao backend).",
    )
    taxasContratuais: list[TaxaContratual] = Field(
        default_factory=list,
        description="Taxas do BASE_COMMISS (BACK-10). Habilitam o custo contratual e o fallback contratual das "
        "vendas do público que nenhuma regra da proposta alcança.",
    )
    pendenciasAceitas: list[PendenciaAceita] = Field(
        default_factory=list, description="Pendências aceitas com ressalva (BACK-7), devolvidas como riscos."
    )
    calibrar: bool = Field(
        default=False,
        description="IA-6: para cada cenário acima do orçamento, buscar uma alternativa de parâmetros verificada "
        "por reexecução. Exige `orcamento`.",
    )
    versoesFontes: dict[str, Any] | None = Field(
        default=None,
        description="`versoesFontes` do recorte (BACK-10). Os hashes (hashRecorte, hashVendas, hashRh…) e a versão "
        "da campanha voltam em `versaoFontes.recorte`.",
    )

    @field_validator("orcamento")
    @classmethod
    def _orcamento_positivo(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("O orçamento deve ser positivo.")
        return value


class GerarProgramaRequest(BaseModel):
    """Gera e valida o programa da simulação ANTES da revisão técnica (IA-2), sem rodar sobre vendas reais."""

    contexto: ContextoProposta = Field(default_factory=ContextoProposta)
    propostas: list[BlocoProposta]
    pedido: str | None = Field(
        default=None,
        description="Mesmo campo de SimularRequest.pedido: indica se há cálculo adicional (ex.: ajuste "
        "sobre a base) que exige código livre em vez do template fixo.",
    )


class ProgramaGeradoResponse(BaseModel):
    origem: Literal["TEMPLATE", "CODIGO_LIVRE"]
    codigo: str | None = Field(
        default=None, description="None quando origem=TEMPLATE (código fixo, não versionado por chamada)."
    )
    assinatura: str = Field(description="sha256 do código (fixo ou gerado); identifica a versão aprovada.")
    premissas: list[str] = Field(default_factory=list)
    pendencias: list[Pendencia] = Field(default_factory=list)
    contexto: ContextoProposta | None = Field(default=None, description="Identificadores recebidos, devolvidos (IA-10).")


class ProgramaArmazenado(BaseModel):
    """Resposta de GET /api/v2/programa/{assinatura}: código recuperado pra revisão posterior."""

    assinatura: str
    codigo: str
    premissas: list[str] = Field(default_factory=list)


SituacaoEnquadramento = Literal["ENQUADRADO", "ACIMA_DO_TETO", "NAO_APLICAVEL"]


class EnquadramentoCenario(BaseModel):
    """Mesmos nomes de `EnquadramentoOrcamentoCenarioDTO` do backend (BACK-8)."""

    cenario: str
    multiplicadorVolume: Decimal
    totalVendasEscopo: int
    orcamentoTeto: Decimal | None = None
    custoTotalProjetado: Decimal
    deltaProjetado: Decimal | None = None
    statusEnquadramento: SituacaoEnquadramento
    dentroDoOrcamento: bool | None = None
    saldoOrcamento: Decimal | None = None
    excedenteOrcamento: Decimal | None = None
    percentualUsoOrcamento: Decimal | None = None


class ResultadoCenario(BaseModel):
    cenario: str
    totalVendas: Decimal
    totalComissao: Decimal = Field(description="Custo proposto: comissão da proposta (com fallback contratual).")
    porBloco: dict[str, Decimal] = Field(
        default_factory=dict,
        description="Comissão por regra (idLocal). `BASE_CONTRATUAL` agrupa as vendas do público sem regra aplicável.",
    )
    porMatricula: dict[str, Decimal] = Field(default_factory=dict)
    # IA-5: comparação contratual x proposta, projeção e orçamento (ausentes quando não calculáveis)
    multiplicadorVendas: Decimal | None = None
    custoContratual: Decimal | None = Field(
        default=None, description="Comissão pelas taxas do BASE_COMMISS sobre as mesmas vendas (referência)."
    )
    diferenca: Decimal | None = Field(default=None, description="Custo proposto − custo contratual.")
    diferencaPercentual: Decimal | None = None
    fatorProjecao: Decimal | None = None
    custoProjetado: Decimal | None = Field(
        default=None, description="Custo proposto × fator de projeção (dias da campanha ÷ 30)."
    )
    deltaProjetado: Decimal | None = None
    qtdVendas: int | None = None
    qtdRegraAplicada: int | None = None
    qtdFallbackContratual: int | None = None
    qtdMudancaFaixa: int | None = Field(
        default=None, description="Vendas cuja regra (ou fallback) muda em relação ao cenário de 100%."
    )
    qtdConflito: int | None = None
    enquadramento: EnquadramentoCenario | None = None


class ItemExclusao(BaseModel):
    """Vendas fora do cálculo, sempre explícitas (nunca viram zero silenciosamente)."""

    codigo: Literal["FORA_DO_PUBLICO", "SEM_TAXA_CONTRATUAL", "TAXA_CONTRATUAL_AMBIGUA", "CONFLITO_REGRAS"]
    motivo: str
    quantidade: int
    valorVendas: Decimal | None = Field(default=None, description="Soma do valor original dessas vendas.")
    vendaIds: list[str] = Field(default_factory=list, description="Até 50 identificadores, para conferência.")
    impedeEncaminhamento: bool = False


class ResumoOrcamento(BaseModel):
    """Consolidado do enquadramento nos cenários (mesmos nomes de `ResumoEnquadramentoOrcamentoDTO`)."""

    orcamentoCampanha: Decimal | None = None
    diasInclusivos: int
    fatorProjecao: Decimal
    totalVendasEscopoComum: int
    escopoConsistenteQuatroCenarios: bool
    statusCenario100: SituacaoEnquadramento
    valorEncaminhamento: Decimal | None = Field(
        default=None, description="Custo projetado do cenário de 100%: valor usado por BACK-4 para a aprovação."
    )
    aptoEncaminhamentoGerente: bool
    motivoBloqueioEncaminhamento: str | None = None


class AlteracaoParametro(BaseModel):
    """Parâmetro de regra alterado por uma alternativa de calibração (para o usuário aplicar ao rascunho)."""

    idLocal: str
    campo: Literal["taxa", "bonus.percentual", "bonus.valorFixo"]
    antes: Decimal
    depois: Decimal


StatusCalibracao = Literal["ENQUADRADA", "SEM_SOLUCAO_VIAVEL", "NAO_NECESSARIA", "FALHA"]


class Calibracao(BaseModel):
    """Alternativa de ajuste para UM cenário (IA-6). Independente das alternativas dos outros cenários."""

    cenario: str
    multiplicadorVendas: Decimal
    status: StatusCalibracao
    orcamento: Decimal
    custoProjetadoOriginal: Decimal | None = None
    custoProjetadoRecalculado: Decimal | None = Field(
        default=None, description="Custo projetado obtido REEXECUTANDO o programa com os parâmetros alterados."
    )
    custoPropostoRecalculado: Decimal | None = None
    folga: Decimal | None = Field(default=None, description="Orçamento − custo projetado recalculado.")
    custoProjetadoMinimo: Decimal | None = Field(
        default=None, description="Custo com os parâmetros no mínimo (só em SEM_SOLUCAO_VIAVEL)."
    )
    fatorAjuste: Decimal | None = Field(default=None, description="Fator aplicado a taxas e bônus (0 < λ ≤ 1).")
    alteracoes: list[AlteracaoParametro] = Field(default_factory=list)
    tentativas: int = Field(description="Reexecuções do programa usadas nesta busca.")
    assinaturaPrograma: str
    motivo: str | None = None


TipoExplicacao = Literal[
    "SEM_ORCAMENTO", "DENTRO_DO_ORCAMENTO", "ACIMA_DO_ORCAMENTO",
    "SUGESTAO_VALIDADA", "SEM_SOLUCAO_VIAVEL", "SUGESTAO_INDISPONIVEL",
]


class ExplicacaoCenario(BaseModel):
    """
    Explicação determinística de UM cenário (IA-7). Todo número citado em `resumo`/`limitacoes` está em
    `numeros` com o valor exato devolvido pela simulação/calibração; o texto nunca altera números.
    """

    execucaoId: str | None = None
    assinaturaPrograma: str | None = None
    cenario: str
    multiplicadorVendas: Decimal
    tipo: TipoExplicacao
    resumo: str
    numeros: dict[str, Decimal] = Field(default_factory=dict)
    limitacoes: list[str] = Field(default_factory=list)


class SimularResponse(BaseModel):
    origem: Literal["TEMPLATE", "CODIGO_LIVRE"]
    simulacao: Literal["SIMULACAO_SANDBOX"] = "SIMULACAO_SANDBOX"
    aviso: str = "Resultado de simulação. Não substitui a apuração oficial."
    resultados: list[ResultadoCenario] = Field(default_factory=list)
    observacoes: list[str] = Field(default_factory=list)
    codigoExecutado: str | None = None
    assinaturaPrograma: str | None = Field(
        default=None, description="sha256 do código executado (TEMPLATE fixo ou código livre aprovado)."
    )
    versaoFontes: dict[str, Any] = Field(
        default_factory=dict,
        description="Rastreabilidade das fontes usadas: origem dos dados (RECORTE_BACKEND|CONSULTA_AGENTE), "
        "competência e quantidade de vendas.",
    )
    orcamento: ResumoOrcamento | None = Field(
        default=None, description="Enquadramento orçamentário consolidado (IA-5). Ausente quando não há números."
    )
    exclusoes: list[ItemExclusao] = Field(default_factory=list)
    riscos: list[str] = Field(default_factory=list, description="Ressalvas que acompanham os números (ex.: pendências aceitas).")
    calibracoes: list[Calibracao] = Field(default_factory=list, description="IA-6: uma entrada por cenário.")
    statusSugestoes: Literal["OK", "FALHA", "NAO_SOLICITADA"] = Field(
        default="NAO_SOLICITADA",
        description="FALHA = ao menos um cenário não pôde ser calibrado; nenhuma alternativa foi inventada para ele.",
    )
    explicacoes: list[ExplicacaoCenario] = Field(
        default_factory=list, description="IA-7: uma explicação por cenário com números, sem LLM."
    )
    contexto: ContextoProposta | None = Field(default=None, description="Identificadores recebidos, devolvidos (IA-10).")
    pendencias: list[Pendencia] = Field(default_factory=list)
    trilhaFerramentas: list[EvidenciaTool] = Field(default_factory=list)
