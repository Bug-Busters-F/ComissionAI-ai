"""Prompt de decisão do agente: escolher a próxima consulta entre as lacunas abertas."""

import json
from typing import Any

PROMPT_SISTEMA_AGENTE = """Você coordena a validação de uma proposta de regras de comissão.
Há LACUNAS: informações que podem ser resolvidas consultando o sistema. Escolha a PRÓXIMA ação.

REGRAS:
- Você só PEDE a consulta; o sistema valida e executa. Você nunca conclui dados por conta própria.
- Escolha `acao=CONSULTAR` com `lacunaId` (um dos ids listados) e a `ferramenta` adequada.
- Em `argumentos` você pode reescrever o termo de público para facilitar a busca (ex.: "gerentes" → "gerente de loja"),
  mas NUNCA invente códigos, matrículas ou valores. Se não tiver certeza, deixe `argumentos` null (usa o padrão).
- Não repita consultas já feitas (veja HISTÓRICO).
- Escolha `acao=FINALIZAR` quando restarem apenas lacunas que a consulta não resolveria ou o histórico mostrar que já foram tentadas.
- Ambiguidade (várias opções) NÃO se resolve por escolha sua: ela vira pergunta ao usuário.
"""


def montar_prompt_decisao(
    lacunas: list[dict[str, Any]],
    ferramentas: list[dict[str, Any]],
    historico: list[dict[str, Any]],
) -> str:
    return f"""{PROMPT_SISTEMA_AGENTE}
FERRAMENTAS DISPONÍVEIS:
{json.dumps(ferramentas, ensure_ascii=False, separators=(",", ":"))}

LACUNAS ABERTAS:
{json.dumps(lacunas, ensure_ascii=False, separators=(",", ":"), default=str)}

HISTÓRICO DE CONSULTAS:
{json.dumps(historico, ensure_ascii=False, separators=(",", ":"), default=str)}

Decida a próxima ação conforme o esquema JSON solicitado:
"""
