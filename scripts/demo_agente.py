"""
Demonstração reproduzível do agente (IA-4), sem LLM real nem backend real.

Mostra: análise do pedido → decisões → consultas → proposta com pendências, com a trilha de ferramentas.
Uso (a partir da raiz do repositório):  PYTHONPATH=src python scripts/demo_agente.py
"""

import json
import os
import sys
from datetime import date
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.core.agente import AgenteInterpretador  # noqa: E402
from app.schemas.proposta import InterpretarRequestV2  # noqa: E402
from app.tools import BackendClient, criar_registry  # noqa: E402

TEXTO = "3% para gerentes da loja 75 e a matrícula MATRIC-9 ganha 5% em dezembro"


def backend(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    if p.endswith("/cargos"):
        return httpx.Response(200, json={"encontrado": True, "itens": [
            {"codigo": 150, "descricao": "GERENTE DE LOJA"}, {"codigo": 150, "descricao": "GERENTE QUIOSQUE"}]})
    if "/matriculas/" in p:
        return httpx.Response(200, json={"encontrado": True, "matricula": "MATRIC-9", "codLoja": 75, "codCargo": 100})
    if p.endswith("/regras-concorrentes"):
        return httpx.Response(200, json={"conflitos": []})
    return httpx.Response(404)


def llm(prompt: str, schema: dict) -> dict:
    if "PEDIDO DO GESTOR PARA PROCESSAR" in prompt:
        return {
            "regras": [
                {"trecho_origem": "3% para gerentes da loja 75", "taxa_raw": "3%", "cargo_raw": "gerentes", "loja_raw": "75"},
                {"trecho_origem": "a matrícula MATRIC-9 ganha 5%", "taxa_raw": "5%", "matricula_raw": "MATRIC-9"},
            ],
            "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
        }
    # decisão do agente: sempre a primeira lacuna listada
    lacuna = json.loads(prompt.split("LACUNAS ABERTAS:\n")[1].split("\n")[0])[0]
    return {"acao": "CONSULTAR", "lacunaId": lacuna["id"], "ferramenta": lacuna["ferramenta"], "justificativa": "demo"}


def main() -> None:
    provider = MagicMock()
    provider.complete.side_effect = lambda prompt, response_schema: llm(prompt, response_schema)
    client = BackendClient(base_url="http://backend-demo", transport=httpx.MockTransport(backend))
    agente = AgenteInterpretador(provider, criar_registry(client))
    resposta = agente.executar(InterpretarRequestV2(texto=TEXTO, dataReferencia=date(2026, 9, 7)))

    print(f"Pedido: {TEXTO}\nStatus: {resposta.status}\n")
    for p in resposta.propostas:
        print(f"[{p.idLocal}] taxa={p.taxa} condicoes={p.condicoes.model_dump(exclude_none=True)}")
        for pend in p.pendencias:
            print(f"     pendência {pend.codigo.value}: {pend.mensagem}")
    print("\nTrilha de ferramentas:")
    for e in resposta.trilhaFerramentas:
        print(f"  passo {e.passo}: {e.ferramenta} -> {e.status} ({e.resumo}) blocos={e.blocosAfetados}")


if __name__ == "__main__":
    main()
