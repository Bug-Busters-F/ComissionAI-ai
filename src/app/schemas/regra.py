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
   - `taxa`: Taxa decimal de comissão (BigDecimal/Decimal, intervalo 0 < taxa <= 1.0000).
   - `dataInicio`: Data inicial da vigência (LocalDate/ISO 8601 YYYY-MM-DD).
   - `dataFim`: Data final da vigência (LocalDate/ISO 8601 YYYY-MM-DD | None).
   - `confianca`: Metadado técnico de integração (BigDecimal/Decimal, 0.0 a 1.0). Não é
     campo de negócio da entidade Regra.
   - `pendencias`: Lista de pendências e apontamentos de ambiguidades (List[str]).

2. Dimensões Ausentes / Não Suportadas no Modelo Atual:
   - `marca`, `loja`, `cargo`, `matricula` (antigo objeto `publico`): NÃO pertencem ao modelo
     de dados MVP de Regra.
   - `operacao`, `percentual` (substituído por `taxa`), `inicio`/`fim` (substituídos por
     `dataInicio`/`dataFim`): NÃO devem ser gerados.
   - `status`, `id`, `campanha_id`, `criadoEm`, `atualizadoEm`, `removidoEm`: Controlados
     exclusivamente pelo Backend / Banco de Dados.
   - `texto_original`: Não faz parte da resposta da IA.

3. Representação de Campos Ausentes ou Ambíguos:
   - Durante a interpretação, campos não identificados retornam explicitamente como `None` (`null`),
     e uma mensagem descritiva do problema é adicionada à lista `pendencias`.
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
    """

    texto: str = Field(
        ...,
        description="Comando em linguagem natural digitado pelo gestor.",
        examples=["Pagar 5% no canal ecommerce durante dezembro"],
    )
    contexto: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadados contextuais opcionais (ex.: ano_referencia, canal_padrao).",
        examples=[{"canal_padrao": "ECOMMERCE", "ano_referencia": 2026}],
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "texto": "Pagar 5% no canal ecommerce durante dezembro",
                "contexto": {
                    "canal_padrao": "ECOMMERCE",
                    "ano_referencia": 2026,
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
        description="Canal de venda normalizado em caixa alta (ex.: ECOMMERCE, LOJA_FISICA).",
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
                    "canal": "ECOMMERCE",
                    "taxa": 0.0500,
                    "dataInicio": "2026-12-01",
                    "dataFim": "2026-12-31",
                    "confianca": 0.95,
                    "pendencias": [],
                },
                {
                    "canal": "ECOMMERCE",
                    "taxa": 0.0500,
                    "dataInicio": "2026-10-01",
                    "dataFim": None,
                    "confianca": 0.90,
                    "pendencias": [],
                },
                {
                    "canal": None,
                    "taxa": None,
                    "dataInicio": None,
                    "dataFim": None,
                    "confianca": 0.30,
                    "pendencias": [
                        "Canal de vendas não identificado.",
                        "Percentual de comissão não identificado.",
                        "Data de início da vigência não identificada.",
                    ],
                },
            ]
        },
    )
