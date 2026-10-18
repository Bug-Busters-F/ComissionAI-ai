"""
Esquema intermediário de extração bruta pelo LLM (Task S1-A04).

Este esquema é usado exclusivamente como `response_schema` para a chamada estruturada
ao provedor de LLM. Ele permite que o modelo extraia termos textuais/brutos de taxas,
períodos de vigência, canal e dimensões de negócio (marca, loja, cargo) sem realizar
conversões determinísticas, as quais são delegadas às camadas determinísticas em Python.
"""

from pydantic import BaseModel, ConfigDict, Field


class InterpretacaoRegraRawLLM(BaseModel):
    """
    Estrutura bruta extraída pelo modelo de linguagem.
    """

    canal: str | None = Field(
        default=None,
        description="Nome ou código textual do canal de venda identificado (ex: ECOMMERCE, LOJA_FISICA, WHATSAPP).",
    )
    taxa_raw: str | None = Field(
        default=None,
        description="Expressão textual ou percentual da comissão (ex: '5%', '3,5%', '0.05', '5 por cento').",
    )
    vigencia_inicio_raw: str | None = Field(
        default=None,
        description="Expressão textual ou data referente ao início da vigência (ex: 'dezembro', '2026-10-01', '01/11/2026', 'a partir de outubro').",
    )
    vigencia_fim_raw: str | None = Field(
        default=None,
        description=(
            "Expressão textual ou data referente ao término da vigência se explicitada "
            "(ex: 'dezembro', '2026-12-31', '31/12/2026'). None se não informada."
        ),
    )
    criterios_nao_suportados: list[str] = Field(
        default_factory=list,
        description=(
            "Lista de critérios ou dimensões mencionadas que NÃO são suportadas no MVP "
            "(ex: 'produto XYZ', 'região Sul', 'categoria smartphones'). "
            "NÃO incluir marca, loja, cargo ou canal — esses são suportados e possuem campos próprios."
        ),
    )
    ambiguidades_ou_duvidas: list[str] = Field(
        default_factory=list,
        description="Lista de ambiguidades, termos vagos ou inconsistências identificadas no texto.",
    )
    marca_raw: str | None = Field(
        default=None,
        description=(
            "Nome ou expressão textual da marca identificada no texto "
            "(ex: 'PRETO', 'marca Branco'). None se não mencionada."
        ),
    )
    loja_raw: str | None = Field(
        default=None,
        description=(
            "Código numérico ou expressão textual da loja identificada no texto "
            "(ex: '75', 'loja 35'). None se não mencionada."
        ),
    )
    cargo_raw: str | None = Field(
        default=None,
        description=(
            "Nome ou expressão textual do cargo/função identificado no texto "
            "(ex: 'vendedores', 'gerentes de loja', 'ASSISTENTE DE VENDAS'). "
            "None se não mencionado."
        ),
    )

    model_config = ConfigDict(
        extra="ignore",
    )


class RegraRawLLM(BaseModel):
    """
    Uma regra extraída de um pedido com várias regras (Sprint 2, IA-2).

    Tudo permanece textual/bruto: a normalização é determinística em Python.
    `trecho_origem` deve ser copiado literalmente do pedido.
    """

    trecho_origem: str = Field(
        description="Trecho LITERAL do pedido do gestor que originou esta regra (copie, não parafraseie)."
    )
    canal: str | None = Field(default=None, description="Canal de venda mencionado para esta regra.")
    marca_raw: str | None = Field(default=None, description="Marca mencionada para esta regra.")
    loja_raw: str | None = Field(default=None, description="Loja (código ou nome) mencionada.")
    cargo_raw: str | None = Field(default=None, description="Cargo/função mencionado.")
    matricula_raw: str | None = Field(
        default=None, description="Matrícula individual de colaborador, se o pedido citar uma."
    )
    taxa_raw: str | None = Field(
        default=None, description="Taxa absoluta de comissão como aparece no texto (ex.: '3%')."
    )
    operacao_raw: str | None = Field(
        default=None,
        description=(
            "Expressão de AJUSTE sobre a taxa base em vez de taxa absoluta "
            "(ex.: 'mais 1 ponto percentual', 'aumentar 10%'). None se a taxa é absoluta."
        ),
    )
    faixa_min_raw: str | None = Field(default=None, description="Limite mínimo de valor de venda (texto).")
    faixa_max_raw: str | None = Field(default=None, description="Limite máximo de valor de venda (texto).")
    faixa_min_inclusivo: bool | None = Field(
        default=None, description="True se o mínimo está incluído ('a partir de'); False se excluído ('acima de')."
    )
    faixa_max_inclusivo: bool | None = Field(
        default=None, description="True se o máximo está incluído ('até'); False se excluído ('abaixo de')."
    )
    bonus_percentual_raw: str | None = Field(
        default=None, description="Adicional percentual sobre a venda (ex.: 'mais 1% de bônus')."
    )
    bonus_valor_raw: str | None = Field(
        default=None, description="Adicional em valor fixo por venda (ex.: 'R$ 50 por venda')."
    )
    vigencia_inicio_raw: str | None = Field(
        default=None, description="Início de vigência citado ESPECIFICAMENTE para esta regra, se houver."
    )
    vigencia_fim_raw: str | None = Field(
        default=None, description="Fim de vigência citado ESPECIFICAMENTE para esta regra, se houver."
    )
    criterios_nao_suportados: list[str] = Field(
        default_factory=list,
        description="Critérios desta regra fora do suporte (produto, região, meta de faturamento...).",
    )
    ambiguidades_ou_duvidas: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class InterpretacaoCampanhaRawLLM(BaseModel):
    """Extração bruta de um pedido que pode conter várias regras."""

    regras: list[RegraRawLLM] = Field(default_factory=list)
    vigencia_inicio_raw: str | None = Field(
        default=None, description="Início de vigência comum da campanha, se o pedido citar."
    )
    vigencia_fim_raw: str | None = Field(
        default=None, description="Fim de vigência comum da campanha, se o pedido citar."
    )
    trechos_nao_mapeados: list[str] = Field(
        default_factory=list,
        description="Trechos literais do pedido que NÃO viraram regra (incompletos ou sem sentido de regra).",
    )

    model_config = ConfigDict(extra="ignore")
