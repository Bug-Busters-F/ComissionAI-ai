"""Prompts da simulação: extração dos cenários do pedido e geração de código livre."""

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.simulacao.validador import BUILTINS_PERMITIDOS, IMPORTS_PERMITIDOS


class CenariosPedido(BaseModel):
    """O LLM só EXTRAI; a escolha template x código livre é determinística sobre `calculo_adicional`."""

    cenarios: list[dict[str, Any]] = Field(
        default_factory=list,
        description='Cenários pedidos: [{"nome": "...", "multiplicadorVendas": 1.2}]. Vazio se o pedido não citar.',
    )
    calculo_adicional: str | None = Field(
        default=None,
        description=(
            "Descrição do cálculo EXTRA que o pedido exige além de comissão por regra e cenários de "
            "multiplicador de vendas (ex.: ranking, percentis, comparação com orçamento, custo por loja). "
            "null se o pedido se resolve só com as regras e os cenários."
        ),
    )


class CodigoGerado(BaseModel):
    codigo: str = Field(description="Código Python completo, com a função simular(vendas, regras, cenario).")
    premissas: list[str] = Field(default_factory=list, description="Premissas assumidas, em português.")


def montar_prompt_cenarios(pedido: str) -> str:
    return f"""Extraia os CENÁRIOS de uma simulação de comissões a partir do pedido do gestor.
- Cenário = nome + multiplicador sobre o valor das vendas (ex.: "vendas +20%" => 1.2; "vendas -10%" => 0.9).
- Não invente cenários que o pedido não cite. Se o pedido não citar nenhum, devolva a lista vazia.
- `calculo_adicional`: preencha SOMENTE se o pedido pedir algo além de comissão por regra e cenários
  (ranking, percentil, comparação com orçamento, agrupamentos especiais). Caso contrário, null.

PEDIDO: "{pedido}"
"""


def montar_prompt_codigo(calculo_adicional: str, esquema_dados: dict[str, Any], amostra: dict[str, Any]) -> str:
    imports = ", ".join(sorted(IMPORTS_PERMITIDOS))
    builtins = ", ".join(sorted(b for b in BUILTINS_PERMITIDOS if b[0].islower()))
    return f"""Escreva UMA função Python pura `simular(vendas, regras, cenario)` que calcula o resultado pedido.

CONTRATO (inegociável):
- Assinatura exata: def simular(vendas, regras, cenario).
- `vendas`: lista de dicts {json.dumps(esquema_dados.get("vendas"), ensure_ascii=False)}; `valorVenda` é Decimal.
- `regras`: lista de propostas (dicts) {json.dumps(esquema_dados.get("regras"), ensure_ascii=False)}; taxas são Decimal.
- `cenario`: dict {{"nome": str, "multiplicadorVendas": Decimal}}. Aplique o multiplicador ao valor de cada venda.
- Retorne um dict JSON-serializável com: "cenario" (str), "totalVendas", "totalComissao" (Decimal, escala 2),
  "porBloco" (dict idLocal -> Decimal), "porMatricula" (dict matricula -> Decimal) e, se útil, outras chaves simples.
- Dinheiro em Decimal com quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).
- Regra de comissão: uma única regra por venda, a de maior especificidade
  (matrícula 16, loja 8, cargo 4, canal 2, marca 1); comissão = valor×taxa (+ bônus percentual + bônus fixo).

PERMITIDO SOMENTE:
- Imports: {imports}.
- Builtins: {builtins}.
PROIBIDO: classes, with, yield, global, recursão, `while True`, eval/exec/open/getattr/type/print,
atributos que começam com "__", qualquer outro import. Máximo ~120 linhas, sem comentários longos.
Se violar qualquer item, o código será REJEITADO sem execução.

CÁLCULO EXTRA PEDIDO: {calculo_adicional}

AMOSTRA SINTÉTICA DOS DADOS (não são dados reais):
{json.dumps(amostra, ensure_ascii=False, default=str)}

Devolva `codigo` e `premissas` (liste o que você assumiu).
"""
