"""
Schemas Pydantic para o fluxo de interpretação de regras de comissão (Task S1-A02).

Este módulo define os esquemas compartilhados entre o serviço de IA (Python) e o
Backend (Spring Boot), rigorosamente alinhados com o contrato S1-B02 e ContratoBackend.md.

================================================================================
REGISTRO DE DIMENSÕES DO MODELO (S1-A02)
================================================================================
1. Dimensões Suportadas no MVP:
   - `canal`: Canal de venda (String em caixa alta, ex: ECOMMERCE, LOJA_FISICA, WHATSAPP).
     * IMPORTANTE: O canal NÃO pode ser inferido automaticamente como marca ou loja.
     * Qualquer alteração/substituição do canal no backlog exige alinhamento com o cliente.
     * `canal` é NULLABLE no banco (tb_regra.canal passou a ser opcional após Correção 2).
   - `codMarca`: Código numérico da marca (Integer | None). Ex: 10 = PRETO.
   - `descrMarca`: Nome da marca em maiúsculas (String | None). Ex: "PRETO".
   - `codCargo`: Código numérico do cargo (Integer | None). Ex: 100 = VENDEDOR LOJA.
   - `descriCargo`: Descrição da função (String | None). Ex: "VENDEDOR LOJA".
     * IMPORTANTE: `codCargo` e `descriCargo` são resolvidos em conjunto. Quando
       houver ambiguidade entre funções que compartilham o mesmo código numérico (ex: 150
       para "GERENTE DE LOJA" ou "GERENTE QUIOSQUE"), `codCargo` retorna o código comum (150)
       e `descriCargo` retorna None acompanhado de pendência descritiva. Se os candidatos
       possuírem códigos distintos, ambos retornam None.
   - `codLoja`: Código numérico da loja (Integer | None). Ex: 75.
   - `taxa`: Taxa decimal de comissão (BigDecimal/Decimal, intervalo 0 < taxa <= 1.0000).
   - `dataInicio`: Data inicial da vigência (LocalDate/ISO 8601 YYYY-MM-DD).
   - `dataFim`: Data final da vigência (LocalDate/ISO 8601 YYYY-MM-DD | None).
   - `confianca`: Metadado técnico de integração (BigDecimal/Decimal, 0.0 a 1.0). Não é
     campo de negócio da entidade Regra.
   - `pendencias`: Lista de pendências e apontamentos de ambiguidades (List[str]).

2. Dimensões Ausentes / Não Suportadas no Modelo Atual:
   - `matricula`: Não faz parte do escopo de Sprint 1.
   - `operacao`, `percentual` (substituído por `taxa`), `inicio`/`fim` (substituídos por
     `dataInicio`/`dataFim`): NÃO devem ser gerados.
   - `status`, `id`, `campanha_id`, `criadoEm`, `atualizadoEm`, `removidoEm`: Controlados
     exclusivamente pelo Backend / Banco de Dados.
   - `texto_original`: Não faz parte da resposta da IA.

3. Representação de Campos Ausentes ou Ambíguos:
   - Durante a interpretação, campos não identificados retornam explicitamente como `None` (`null`).
   - O Backend decide se campos nulos geram pendências; a IA apenas sinaliza em `pendencias`
     quando há ambiguidade real (ex.: dois cargos possíveis para o mesmo código).
   - Quando `dataFim` for `None`, a IA não inventa vigência; o Backend adiciona a pendência
     informativa de que aplicará 30 dias de vigência padrão na confirmação.
================================================================================
"""

from datetime import date
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InterpretacaoRegraRequest(BaseModel):
    """
    Payload de entrada enviado pelo Backend Spring Boot para o serviço de IA.
    Espelha o DTO InterpretacaoRegraRequest do Spring Boot.

    O campo `contexto.dicionario_dimensoes` pode conter:
    - `marcas`: dict[str, str] — mapa de código (str) → nome da marca (ex: {"10": "PRETO"})
    - `cargos`: dict[str, str] — mapa de código (str) → nome do cargo (ex: {"100": "VENDEDOR LOJA"})
    - `canais`: list[str] — lista de canais disponíveis (ex: ["LOJA_FISICA", "ECOMMERCE"])
    """

    texto: str = Field(
        ...,
        min_length=1,
        description="Comando em linguagem natural digitado pelo gestor.",
        examples=["Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026"],
    )

    @field_validator("texto")
    @classmethod
    def validar_texto_nao_vazio(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("O texto do comando não pode ser vazio ou conter apenas espaços.")
        return value
    contexto: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Metadados contextuais opcionais. Pode conter `ano_referencia` (int), "
            "`canal_padrao` (str) e `dicionario_dimensoes` com catálogo de marcas, cargos e canais."
        ),
        examples=[{
            "ano_referencia": 2026,
            "dicionario_dimensoes": {
                "marcas": {"10": "PRETO", "20": "BRANCO"},
                "cargos": {"100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA"},
                "canais": ["LOJA_FISICA", "ECOMMERCE"],
            },
        }],
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "texto": "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
                "contexto": {
                    "ano_referencia": 2026,
                    "dicionario_dimensoes": {
                        "marcas": {"10": "PRETO", "20": "BRANCO", "30": "AZUL"},
                        "cargos": {"100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA", "200": "VENDEDOR BALCAO"},
                        "canais": ["LOJA_FISICA", "ECOMMERCE", "BALCAO", "QUIOSQUE", "APP", "PADRAO"],
                    },
                },
            }
        },
    )


class InterpretacaoRegraResponse(BaseModel):
    """
    Proposta de regra estruturada retornada pelo serviço de IA para o Backend Spring Boot.
    Espelha o DTO InterpretacaoRegraResponse do Spring Boot.
    """

    canal: str | None = Field(
        default=None,
        description="Canal de venda normalizado em caixa alta (ex.: ECOMMERCE, LOJA_FISICA). Opcional — o banco aceita null.",
    )
    codMarca: int | None = Field(
        default=None,
        description="Código numérico da marca (ex.: 10 para PRETO). None se não identificada no texto.",
    )
    descrMarca: str | None = Field(
        default=None,
        description="Nome da marca em maiúsculas (ex.: 'PRETO'). None se não identificada no texto.",
    )
    codCargo: int | None = Field(
        default=None,
        description="Código numérico do cargo (ex.: 100 para VENDEDOR LOJA). None se não identificado ou ambíguo.",
    )
    descriCargo: str | None = Field(
        default=None,
        description="Descrição da função (ex.: 'VENDEDOR LOJA'). Resolvido em conjunto com codCargo. None se ambíguo.",
    )
    codLoja: int | None = Field(
        default=None,
        description="Código numérico da loja (ex.: 75). None se não identificada no texto.",
    )
    taxa: Decimal | None = Field(
        default=None,
        description="Taxa de comissão decimal (ex: 0.0500 = 5%, 1.0000 = 100%). Deve satisfazer 0 < taxa <= 1.0000.",
    )
    dataInicio: date | None = Field(
        default=None,
        description="Data de início da vigência da regra no formato ISO 8601 (YYYY-MM-DD).",
    )
    dataFim: date | None = Field(
        default=None,
        description="Data de término da vigência (YYYY-MM-DD). None indica ausência de especificação explícita.",
    )
    confianca: Decimal | None = Field(
        default=None,
        description="Metadado técnico da IA indicando o nível de confiança (0.0 a 1.0). Não é campo de negócio persistido.",
    )
    pendencias: list[str] = Field(
        default_factory=list,
        description="Lista de pendências, ambiguidades ou dados faltantes identificados na interpretação.",
    )

    @field_validator("canal", mode="before")
    @classmethod
    def normalizar_canal(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned if cleaned else None
        return value

    @field_validator("descrMarca", mode="before")
    @classmethod
    def normalizar_descr_marca(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned if cleaned else None
        return value

    @field_validator("descriCargo", mode="before")
    @classmethod
    def normalizar_descri_cargo(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip().upper()
            return cleaned if cleaned else None
        return value

    @field_validator("taxa")
    @classmethod
    def validar_taxa(cls, value: Decimal | None) -> Decimal | None:
        if value is not None:
            if value <= Decimal("0") or value > Decimal("1.0000"):
                raise ValueError(
                    f"A taxa deve ser maior que 0 e menor ou igual a 1.0000 (100%). Valor recebido: {value}"
                )
        return value

    @field_validator("confianca")
    @classmethod
    def validar_confianca(cls, value: Decimal | None) -> Decimal | None:
        if value is not None:
            if value < Decimal("0") or value > Decimal("1.0000"):
                raise ValueError(
                    f"O nível de confiança deve estar entre 0.0 e 1.0000. Valor recebido: {value}"
                )
        return value

    @model_validator(mode="after")
    def validar_vigencia(self) -> "InterpretacaoRegraResponse":
        if self.dataInicio is not None and self.dataFim is not None:
            if self.dataFim < self.dataInicio:
                raise ValueError(
                    f"A dataFim ({self.dataFim}) não pode ser anterior à dataInicio ({self.dataInicio})."
                )
        return self

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "canal": "LOJA_FISICA",
                    "codMarca": 10,
                    "descrMarca": "PRETO",
                    "codCargo": 100,
                    "descriCargo": "VENDEDOR LOJA",
                    "codLoja": 75,
                    "taxa": 0.0350,
                    "dataInicio": "2026-10-01",
                    "dataFim": "2026-10-31",
                    "confianca": 0.95,
                    "pendencias": [],
                },
                {
                    "canal": "ECOMMERCE",
                    "codMarca": None,
                    "descrMarca": None,
                    "codCargo": None,
                    "descriCargo": None,
                    "codLoja": None,
                    "taxa": 0.0500,
                    "dataInicio": "2026-10-01",
                    "dataFim": None,
                    "confianca": 0.90,
                    "pendencias": [],
                },
                {
                    "canal": None,
                    "codMarca": None,
                    "descrMarca": None,
                    "codCargo": 150,
                    "descriCargo": None,
                    "codLoja": None,
                    "taxa": None,
                    "dataInicio": None,
                    "dataFim": None,
                    "confianca": 0.30,
                    "pendencias": [
                        "Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'.",
                        "Percentual de comissão não identificado.",
                        "Data de início da vigência não identificada.",
                    ],
                },
            ]
        },
    )
