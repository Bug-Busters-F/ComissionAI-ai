"""
Construção e montagem de prompts para interpretação de regras (Task S1-A04).

Este módulo compõe as instruções para o LLM, incluindo catálogo de dimensões
(canais, marcas, cargos), regras de negócio do MVP, tratamento de critérios não
suportados e exemplos few-shot (com cenários de sucesso e geração de pendências).
"""

import json
from typing import Any


PROMPT_SISTEMA_REGRAS = """Você é um extrator de regras de comissão comercial para o motor MVP do sistema Dom Rock.

OBJETIVO:
Extraia somente as informações explicitamente presentes na regra do gestor.
Não invente, complete ou corrija informações ausentes.

DIMENSÕES SUPORTADAS NO MVP:
- canal: canal de venda.
- taxa_raw: percentual/taxa exatamente como aparece no texto.
- vigencia_inicio_raw: expressão de início da vigência.
- vigencia_fim_raw: expressão de fim da vigência.
- marca_raw: marca mencionada.
- loja_raw: código ou identificação da loja.
- cargo_raw: cargo/função mencionado.

CATÁLOGO:
Quando um catálogo for fornecido, use-o para validar marcas, cargos e canais.
Nunca substitua um valor informado pelo usuário por outro valor do catálogo.

Se um valor mencionado não existir no catálogo:
- não invente um valor;
- não substitua por outro;
- preserve o valor textual em seu campo raw, quando possível;
- registre a ocorrência em ambiguidades_ou_duvidas.

DIMENSÕES NÃO SUPORTADAS NO MVP:
O MVP não suporta:
- categoria de produto ou SKU;
- região geográfica;
- meta de faturamento;
- matrícula/colaborador individual.

Registre somente esses critérios em criterios_nao_suportados.
Marca, loja, cargo e canal nunca devem ser classificados como
criterios_nao_suportados.

REGRAS:
1. Marca, loja, cargo e canal são dimensões independentes.
2. Nunca converta uma dimensão em outra.
3. Não invente taxas, datas, canais, marcas, lojas ou cargos.
4. Preserve os valores raw conforme aparecem no texto.
5. Use null quando um campo não for mencionado.
6. Use ambiguidades_ou_duvidas quando houver informação mencionada,
   mas insuficiente ou ambígua para determinar o valor com segurança.
7. A ausência de um campo, por si só, não é uma ambiguidade.
8. Não faça conversões numéricas ou de datas nesta etapa.
9. Retorne somente os campos definidos no schema.
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
    contexto_str = json.dumps(contexto_resumido, ensure_ascii=False, separators=(",", ":"))

    catalogo_str = _formatar_catalogo(contexto)

    exemplos_formatados = []
    for i, ex in enumerate(FEW_SHOT_EXAMPLES, 1):
        exemplos_formatados.append(
            f"Exemplo {i}:\n"
            f"Entrada: \"{ex['input']}\"\n"
            f"Saída: {json.dumps(ex['output'], ensure_ascii=False, separators=(",", ":"))}"
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
