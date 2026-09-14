"""
Construção e montagem de prompts para interpretação de regras (Task S1-A04).

Este módulo compõe as instruções para o LLM, incluindo catálogo de canais,
regras de negócio do MVP, tratamento de critérios não suportados e exemplos
few-shot (com cenários de sucesso e geração de pendências).
"""

import json
from typing import Any


PROMPT_SISTEMA_REGRAS = """Você é um assistente especialista em interpretar regras de comissão comercial para estruturação no motor MVP do sistema Dom Rock.

SEU OBJETIVO:
Extrair com precisão os parâmetros da regra de comissão descrita pelo gestor em linguagem natural para o esquema de extração estruturado.

DIMENSÕES SUPORTADAS NO MVP:
1. Canal de Venda (`canal`): Apenas canais válidos do catálogo (ex.: ECOMMERCE, LOJA_FISICA, WHATSAPP, TELEVENDAS, BALCAO).
2. Taxa/Percentual de Comissão (`taxa_raw`): O valor textual do percentual ou taxa (ex.: '5%', '3,5%', '0.05', '5 por cento').
3. Vigência Inicial (`vigencia_inicio_raw`): Expressão temporal de início (ex.: 'dezembro', '2026-10-01', '01/11/2026', 'a partir de outubro', '1º trimestre').
4. Vigência Final (`vigencia_fim_raw`): Expressão temporal de término se informada (ex.: 'dezembro', '2026-12-31', '31/12/2026', '1º trimestre'). Se não informada, retornar null.

DIMENSÕES NÃO SUPORTADAS NO MVP:
O motor do MVP NÃO suporta filtros por:
- Loja física específica (ex.: 'loja 75', 'loja Morumbi')
- Marca específica (ex.: 'marca PRETO', 'marca BRANCO')
- Cargo ou função (ex.: 'vendedores', 'gerentes')
- Matrícula/Colaborador individual
- Categoria de produto ou SKU (ex.: 'smartphones', 'linha branca')
- Região geográfica ou meta de faturamento

REGRAS OBRIGATÓRIAS:
1. NUNCA tente converter critérios não suportados (loja, marca, cargo, produto) em canal. Registre todo critério não suportado na lista `criterios_nao_suportados`.
2. NUNCA invente canais, taxas ou datas não mencionadas. Se uma informação faltar ou estiver vaga, aponte em `ambiguidades_ou_duvidas`.
3. Se o texto for apenas 'em dezembro' ou 'em outubro', tanto `vigencia_inicio_raw` quanto `vigencia_fim_raw` devem registrar o mês correspondente. Se for 'a partir de outubro', `vigencia_inicio_raw` é 'outubro' e `vigencia_fim_raw` é null.
4. Na dúvida, gere pendência. Nunca invente dados.
"""

FEW_SHOT_EXAMPLES = [
    {
        "input": "Pagar 5% no canal ecommerce durante dezembro",
        "output": {
            "canal": "ECOMMERCE",
            "taxa_raw": "5%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
        },
    },
    {
        "input": "Comissão de 3.5% para vendas via whatsapp a partir de 01/10/2026",
        "output": {
            "canal": "WHATSAPP",
            "taxa_raw": "3.5%",
            "vigencia_inicio_raw": "2026-10-01",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
        },
    },
    {
        "input": "3% para os vendedores da loja 75 em dezembro",
        "output": {
            "canal": None,
            "taxa_raw": "3%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": ["loja 75", "vendedores (cargo)"],
            "ambiguidades_ou_duvidas": ["Canal de venda não identificado no texto"],
        },
    },
    {
        "input": "2% na venda de smartphones no balcão no 1º trimestre",
        "output": {
            "canal": "BALCAO",
            "taxa_raw": "2%",
            "vigencia_inicio_raw": "1º trimestre",
            "vigencia_fim_raw": "1º trimestre",
            "criterios_nao_suportados": ["smartphones (categoria de produto)"],
            "ambiguidades_ou_duvidas": [],
        },
    },
    {
        "input": "Dar um bônus especial no próximo mês",
        "output": {
            "canal": None,
            "taxa_raw": None,
            "vigencia_inicio_raw": "próximo mês",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": ["bônus especial"],
            "ambiguidades_ou_duvidas": [
                "Percentual/taxa de comissão não informado",
                "Canal de vendas não informado",
            ],
        },
    },
]


def montar_prompt_interpretacao(
    texto: str,
    contexto: dict[str, Any] | None = None,
) -> str:
    """
    Monta a instrução completa contendo diretrizes, contexto recebido,
    exemplos resolvidos e o comando do usuário.

    Args:
        texto: Frase em linguagem natural digitada pelo gestor.
        contexto: Dicionário com metadados como ano_referencia, data_referencia, canal_padrao.

    Returns:
        String formatada para o prompt do LLM.
    """
    contexto_str = json.dumps(contexto or {}, ensure_ascii=False, indent=2)

    exemplos_formatados = []
    for i, ex in enumerate(FEW_SHOT_EXAMPLES, 1):
        exemplos_formatados.append(
            f"Exemplo {i}:\n"
            f"Entrada: \"{ex['input']}\"\n"
            f"Saída: {json.dumps(ex['output'], ensure_ascii=False)}"
        )

    exemplos_str = "\n\n".join(exemplos_formatados)

    prompt = f"""{PROMPT_SISTEMA_REGRAS}

CONTEXTO DA REQUISIÇÃO:
{contexto_str}

EXEMPLOS DE INTERPRETAÇÃO:
{exemplos_str}

---
COMANDO DO USUÁRIO PARA PROCESSAR:
Texto: "{texto}"

Extraia os campos brutos conforme o esquema JSON solicitado:
"""
    return prompt
