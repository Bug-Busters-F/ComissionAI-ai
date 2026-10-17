"""
Prompt de extração de campanhas com várias regras (Sprint 2, IA-2).

O modelo só EXTRAI texto bruto por regra, com o trecho de origem copiado do pedido.
Normalização, validação e consulta a cadastros são determinísticas (Python/tools).
"""

import json
from typing import Any

from app.core.prompts.regra_prompt import _formatar_catalogo

PROMPT_SISTEMA_CAMPANHA = """Você é um extrator de regras de comissão comercial do sistema Dom Rock.
O pedido do gestor pode conter UMA ou VÁRIAS regras. Extraia cada regra separadamente.

PRINCÍPIOS:
- Extraia somente o que está explícito. Nunca invente taxas, valores, datas, lojas, cargos ou matrículas.
- Use null quando um campo não for mencionado. Preserve os valores como aparecem no texto.
- `trecho_origem` de cada regra deve ser copiado LITERALMENTE do pedido (sem parafrasear).
- Nenhuma condição pode ser descartada: o que não for suportado vai em `criterios_nao_suportados`;
  trechos que não formam uma regra vão em `trechos_nao_mapeados`.

O QUE É UMA REGRA:
- Cada combinação distinta de público (marca, loja, cargo, canal, matrícula) + condição de valor + remuneração.
- "3% para vendedores e 2% para gerentes" são DUAS regras.
- Faixas de valor ("2% até R$ 10 mil e 3% acima") são regras separadas, uma por faixa.
- Comissão individual: preencha `matricula_raw`.
- Bônus adicional sobre a venda: `bonus_percentual_raw` (ex.: "+1%") ou `bonus_valor_raw` (ex.: "R$ 50 por venda").

TAXA ABSOLUTA x AJUSTE:
- "3%" é taxa absoluta: preencha `taxa_raw`.
- "mais 1 ponto percentual", "aumentar 10% sobre a base", "reduzir em 0,5 p.p." são AJUSTES:
  preencha `operacao_raw` com a expressão e deixe `taxa_raw` null. Não calcule o resultado.

FAIXAS DE VALOR (sobre o valor de cada venda):
- "a partir de X": mínimo incluído. "acima de X": mínimo excluído. "até X": máximo incluído. "abaixo de X": máximo excluído.
- Preencha `faixa_min_raw`/`faixa_max_raw` e as flags de inclusão quando o texto permitir deduzir.

VIGÊNCIA:
- Vigência comum da campanha em `vigencia_inicio_raw`/`vigencia_fim_raw` (nível raiz).
- Só preencha a vigência dentro de uma regra se o pedido citar um período ESPECÍFICO para ela.

NÃO SUPORTADO: categoria de produto/SKU, região geográfica, meta de faturamento ou atingimento de meta.
Marca, loja, cargo, canal e matrícula são suportados e nunca vão em `criterios_nao_suportados`.
"Quem bater a meta" => adicione "meta de faturamento" em `criterios_nao_suportados` e mantenha a regra.

AMBIGUIDADE: use `ambiguidades_ou_duvidas` para informação mencionada mas insuficiente. A ausência de um campo não é ambiguidade.
"""

FEW_SHOT_CAMPANHA: list[dict[str, Any]] = [
    {
        "input": "3% para vendedores da loja 75 e 2% para gerentes da loja 75 em dezembro",
        "output": {
            "regras": [
                {"trecho_origem": "3% para vendedores da loja 75", "taxa_raw": "3%", "cargo_raw": "vendedores", "loja_raw": "75"},
                {"trecho_origem": "2% para gerentes da loja 75", "taxa_raw": "2%", "cargo_raw": "gerentes", "loja_raw": "75"},
            ],
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "trechos_nao_mapeados": [],
        },
    },
    {
        "input": "2% nas vendas até R$ 10 mil e 3% nas vendas acima de R$ 10 mil no ecommerce",
        "output": {
            "regras": [
                {"trecho_origem": "2% nas vendas até R$ 10 mil", "taxa_raw": "2%", "canal": "ECOMMERCE",
                 "faixa_max_raw": "R$ 10 mil", "faixa_max_inclusivo": True},
                {"trecho_origem": "3% nas vendas acima de R$ 10 mil", "taxa_raw": "3%", "canal": "ECOMMERCE",
                 "faixa_min_raw": "R$ 10 mil", "faixa_min_inclusivo": False},
            ],
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "trechos_nao_mapeados": [],
        },
    },
    {
        "input": "A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda em outubro de 2026",
        "output": {
            "regras": [
                {"trecho_origem": "A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda",
                 "matricula_raw": "MATRIC-56", "taxa_raw": "6%", "bonus_valor_raw": "R$ 200"},
            ],
            "vigencia_inicio_raw": "outubro de 2026",
            "vigencia_fim_raw": "outubro de 2026",
            "trechos_nao_mapeados": [],
        },
    },
    {
        "input": "5% para quem bater a meta da loja 12. Os gerentes também ganham.",
        "output": {
            "regras": [
                {"trecho_origem": "5% para quem bater a meta da loja 12", "taxa_raw": "5%", "loja_raw": "12",
                 "criterios_nao_suportados": ["meta de faturamento"]},
                {"trecho_origem": "Os gerentes também ganham", "cargo_raw": "gerentes",
                 "ambiguidades_ou_duvidas": ["O percentual dos gerentes não foi informado."]},
            ],
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "trechos_nao_mapeados": [],
        },
    },
    {
        "input": "Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a comissão base em novembro",
        "output": {
            "regras": [
                {"trecho_origem": "Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a comissão base",
                 "cargo_raw": "Vendedores", "marca_raw": "PRETO", "operacao_raw": "mais 1 ponto percentual sobre a comissão base"},
            ],
            "vigencia_inicio_raw": "novembro",
            "vigencia_fim_raw": "novembro",
            "trechos_nao_mapeados": [],
        },
    },
]


def montar_prompt_campanha(texto: str, contexto: dict[str, Any] | None = None) -> str:
    contexto = contexto or {}
    resumo = {k: v for k, v in contexto.items() if k != "dicionario_dimensoes"}
    contexto_str = json.dumps(resumo, ensure_ascii=False, separators=(",", ":"), default=str)
    catalogo = _formatar_catalogo(contexto)
    exemplos = []
    for i, ex in enumerate(FEW_SHOT_CAMPANHA, 1):
        saida = json.dumps(ex["output"], ensure_ascii=False, separators=(",", ":"))
        exemplos.append(f'Exemplo {i}:\nEntrada: "{ex["input"]}"\nSaída: {saida}')
    exemplos_str = "\n\n".join(exemplos)
    return f"""{PROMPT_SISTEMA_CAMPANHA}
{catalogo}

CONTEXTO DA REQUISIÇÃO:
{contexto_str}

EXEMPLOS:
{exemplos_str}

---
PEDIDO DO GESTOR PARA PROCESSAR:
Texto: "{texto}"

Extraia as regras conforme o esquema JSON solicitado:
"""
