"""
Construção e montagem de prompts para interpretação de regras (Task S1-A04).

Este módulo compõe as instruções para o LLM, incluindo catálogo de dimensões
(canais, marcas, cargos), regras de negócio do MVP, tratamento de critérios não
suportados e exemplos few-shot (com cenários de sucesso e geração de pendências).
"""

import json
from typing import Any


PROMPT_SISTEMA_REGRAS = """Você é um assistente especialista em interpretar regras de comissão comercial para estruturação no motor MVP do sistema Dom Rock.

SEU OBJETIVO:
Extrair com precisão os parâmetros da regra de comissão descrita pelo gestor em linguagem natural para o esquema de extração estruturado.

DIMENSÕES SUPORTADAS NO MVP:
1. Canal de Venda (`canal`): Canal informado no texto (ex.: ECOMMERCE, LOJA_FISICA, WHATSAPP, TELEVENDAS, BALCAO). Use APENAS canais do catálogo fornecido no contexto. Se não houver catálogo, use os padrões conhecidos.
2. Taxa/Percentual de Comissão (`taxa_raw`): O valor textual do percentual ou taxa (ex.: '5%', '3,5%', '0.05', '5 por cento').
3. Vigência Inicial (`vigencia_inicio_raw`): Expressão temporal de início (ex.: 'dezembro', '2026-10-01', '01/11/2026', 'a partir de outubro', '1º trimestre').
4. Vigência Final (`vigencia_fim_raw`): Expressão temporal de término se informada (ex.: 'dezembro', '2026-12-31', '31/12/2026', '1º trimestre'). Se não informada, retornar null.
5. Marca (`marca_raw`): Nome ou expressão da marca identificada no texto (ex.: 'PRETO', 'marca Branco'). Use APENAS marcas do catálogo fornecido. Retornar null se não mencionada.
6. Loja (`loja_raw`): Código numérico ou expressão da loja identificada (ex.: '75', 'loja 35'). Retornar null se não mencionada.
7. Cargo/Função (`cargo_raw`): Nome do cargo ou função identificado (ex.: 'vendedores', 'gerentes de loja'). Use APENAS cargos do catálogo fornecido. Retornar null se não mencionado.

DIMENSÕES NÃO SUPORTADAS NO MVP:
O motor do MVP NÃO suporta filtros por:
- Categoria de produto ou SKU (ex.: 'smartphones', 'linha branca')
- Região geográfica ou meta de faturamento
- Matrícula/Colaborador individual

Registre APENAS esses critérios em `criterios_nao_suportados`. NÃO coloque marca, loja, cargo ou canal nessa lista.

REGRAS OBRIGATÓRIAS:
1. NUNCA converta marca, loja ou cargo em canal. São dimensões independentes com campos próprios.
2. NUNCA invente canais, taxas, marcas, cargos ou datas não mencionadas. Se uma informação faltar ou estiver vaga, aponte em `ambiguidades_ou_duvidas`.
3. Se o texto for apenas 'em dezembro' ou 'em outubro', tanto `vigencia_inicio_raw` quanto `vigencia_fim_raw` devem registrar o mês correspondente. Se for 'a partir de outubro', `vigencia_inicio_raw` é 'outubro' e `vigencia_fim_raw` é null.
4. Use o catálogo de marcas e cargos fornecido no contexto para extrair os nomes exatos.
5. Na dúvida, gere pendência em `ambiguidades_ou_duvidas`. Nunca invente dados.
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
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        },
    },
    {
        "input": "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
        "output": {
            "canal": None,
            "taxa_raw": "3.5%",
            "vigencia_inicio_raw": "outubro de 2026",
            "vigencia_fim_raw": "outubro de 2026",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": "PRETO",
            "loja_raw": "75",
            "cargo_raw": "vendedores",
        },
    },
    {
        "input": "Comissão de 3.5% via whatsapp a partir de 01/10/2026",
        "output": {
            "canal": "WHATSAPP",
            "taxa_raw": "3.5%",
            "vigencia_inicio_raw": "2026-10-01",
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
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
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        },
    },
    {
        "input": "Pagar comissão especial para os gerentes",
        "output": {
            "canal": None,
            "taxa_raw": None,
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [
                "Percentual/taxa de comissão não informado",
                "Canal de vendas não informado",
                "Data de início da vigência não informada",
                "Ambiguidade de cargo: 'gerentes' pode referir-se a múltiplas funções no catálogo",
            ],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": "gerentes",
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
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        },
    },
]


def _formatar_catalogo(contexto: dict[str, Any]) -> str:
    """Formata o catálogo de dimensões para inclusão no prompt."""
    dim = contexto.get("dicionario_dimensoes")
    if not isinstance(dim, dict):
        return ""

    linhas = ["\nCATÁLOGO DE DIMENSÕES DISPONÍVEIS (use apenas esses valores):"]

    marcas = dim.get("marcas")
    if isinstance(marcas, dict) and marcas:
        linhas.append("  Marcas (código → nome):")
        for cod, nome in marcas.items():
            linhas.append(f"    {cod}: {nome}")

    cargos = dim.get("cargos")
    if isinstance(cargos, dict) and cargos:
        linhas.append("  Cargos (código → nome):")
        for cod, nome in cargos.items():
            linhas.append(f"    {cod}: {nome}")

    canais = dim.get("canais")
    if isinstance(canais, list) and canais:
        linhas.append(f"  Canais disponíveis: {', '.join(str(c) for c in canais)}")

    return "\n".join(linhas) if len(linhas) > 1 else ""


def montar_prompt_interpretacao(
    texto: str,
    contexto: dict[str, Any] | None = None,
) -> str:
    """
    Monta a instrução completa contendo diretrizes, catálogo de dimensões,
    contexto recebido, exemplos resolvidos e o comando do usuário.

    Args:
        texto: Frase em linguagem natural digitada pelo gestor.
        contexto: Dicionário com metadados como ano_referencia, canal_padrao,
                  dicionario_dimensoes (marcas, cargos, canais).

    Returns:
        String formatada para o prompt do LLM.
    """
    contexto = contexto or {}
    contexto_resumido = {k: v for k, v in contexto.items() if k != "dicionario_dimensoes"}
    contexto_str = json.dumps(contexto_resumido, ensure_ascii=False, indent=2)

    catalogo_str = _formatar_catalogo(contexto)

    exemplos_formatados = []
    for i, ex in enumerate(FEW_SHOT_EXAMPLES, 1):
        exemplos_formatados.append(
            f"Exemplo {i}:\n"
            f"Entrada: \"{ex['input']}\"\n"
            f"Saída: {json.dumps(ex['output'], ensure_ascii=False)}"
        )

    exemplos_str = "\n\n".join(exemplos_formatados)

    prompt = f"""{PROMPT_SISTEMA_REGRAS}
{catalogo_str}

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
