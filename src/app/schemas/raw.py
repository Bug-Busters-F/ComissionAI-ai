"""
Esquema intermediário de extração bruta pelo LLM (Task S1-A04).

Este esquema é usado exclusivamente como `response_schema` para a chamada estruturada
ao provedor de LLM. Ele permite que o modelo extraia termos textuais/brutos de taxas,
períodos de vigência e dimensões não suportadas sem realizar conversões determinísticas,
as quais são delegadas às camadas determinísticas em Python.
"""

from typing import Any
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
        description="Expressão textual ou data referente ao término da vigência se explicitada (ex: 'dezembro', '2026-12-31', '31/12/2026'). None se não informada.",
    )
    criterios_nao_suportados: list[str] = Field(
        default_factory=list,
        description="Lista de critérios ou dimensões mencionadas que NÃO são suportadas no MVP (ex: 'loja 75', 'marca PRETO', 'cargo vendedor', 'produto XYZ').",
    )
    ambiguidades_ou_duvidas: list[str] = Field(
        default_factory=list,
        description="Lista de ambiguidades, termos vagos ou inconsistências identificadas no texto.",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "canal": "ECOMMERCE",
                "taxa_raw": "5%",
                "vigencia_inicio_raw": "dezembro",
                "vigencia_fim_raw": "dezembro",
                "criterios_nao_suportados": [],
                "ambiguidades_ou_duvidas": [],
            }
        },
    )
