"""
IA-9 (BUG-81): validação ponta a ponta dos fluxos do serviço pelas rotas HTTP, com o Spring
simulado por httpx.MockTransport e o LLM falso decidindo como o modelo real (lacuna a lacuna).

Fluxos: interpretação inicial, ajuste com base em versão existente, reinterpretação localizada,
atualização de artefatos após edição manual e falha de ferramenta no meio do fluxo.
"""

import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.api.routes.v2 import get_agente
from app.core.agente import AgenteInterpretador
from app.core.agente.hooks import HooksAjusteSobreBase
from app.main import app
from app.tools import BackendClient, criar_registry

_FERRAMENTA = {
    "PUBLICO": "resolver_publico",
    "MATRICULA": "validar_matricula",
    "BASE": "consultar_base_comissao",
    "CONCORRENCIA": "consultar_regras_concorrentes",
}
_CAMPOS_DE_CONTROLE = {"status", "ativa", "publicada", "versao", "valorComissao", "protocolo", "id"}


def llm_falso(regras):
    """Extração fixa; nas decisões consulta a primeira lacuna listada no prompt."""

    def complete(prompt, response_schema):
        if "PEDIDO DO GESTOR PARA PROCESSAR" in prompt:
            return {"regras": regras, "vigencia_inicio_raw": "2026-12-01", "vigencia_fim_raw": "2026-12-31"}
        lacuna = re.search(r"\b(PUBLICO|MATRICULA|BASE|CONCORRENCIA):[\w-]+", prompt).group(0)
        return {"acao": "CONSULTAR", "lacunaId": lacuna, "ferramenta": _FERRAMENTA[lacuna.split(":")[0]]}

    p = MagicMock()
    p.complete.side_effect = complete
    return p


class SpringFalso:
    """Consultas do backend com dados de um cadastro mínimo; registra as chamadas recebidas."""

    def __init__(self, base=None, base_status=200):
        self.chamadas: list[tuple[str, dict]] = []
        self.base = base if base is not None else {"encontrado": True, "taxa": "0.0250", "competenciaUsada": "2026-12"}
        self.base_status = base_status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        caminho = req.url.path
        corpo = json.loads(req.content) if req.content else dict(req.url.params)
        self.chamadas.append((caminho, corpo))
        if caminho.endswith("/cargos"):
            return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 100, "descricao": "VENDEDOR"}]})
        if caminho.endswith("/marcas"):
            return httpx.Response(200, json={"encontrado": True, "itens": [{"codigo": 10, "descricao": "PRETO"}]})
        if caminho.endswith("/bases"):
            return httpx.Response(self.base_status, json=self.base)
        if caminho.endswith("/regras-concorrentes"):
            return httpx.Response(200, json={"conflitos": []})
        return httpx.Response(404)

    def chamou(self, sufixo: str) -> list[dict]:
        return [c for p, c in self.chamadas if p.endswith(sufixo)]


class TestFluxosIntegrados(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def _usar(self, regras, spring: SpringFalso) -> None:
        registry = criar_registry(
            client=BackendClient(base_url="http://spring", timeout=1, transport=httpx.MockTransport(spring))
        )
        app.dependency_overrides[get_agente] = lambda: AgenteInterpretador(
            llm_falso(regras), registry, hooks=HooksAjusteSobreBase()
        )

    def _interpretar_ajuste_versao_existente(self, spring: SpringFalso) -> dict:
        self._usar(
            [{"trecho_origem": "mais 1 ponto percentual para vendedores da marca preto",
              "operacao_raw": "mais 1 ponto percentual", "cargo_raw": "vendedores", "marca_raw": "preto"}],
            spring,
        )
        r = self.client.post("/api/v2/interpretar", json={
            "texto": "mais 1 ponto percentual para vendedores da marca preto",
            "competencia": "2026-12",
            "contexto": {"campanhaId": "camp-1", "revisao": 4, "origem": "VERSAO_EXISTENTE"},
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_fluxo_1_interpretacao_inicial(self):
        spring = SpringFalso()
        self._usar([{"trecho_origem": "3% para vendedores", "taxa_raw": "3%", "cargo_raw": "vendedores"}], spring)
        r = self.client.post("/api/v2/interpretar", json={"texto": "3% para vendedores", "competencia": "2026-12"})
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        p = corpo["propostas"][0]
        self.assertEqual(corpo["status"], "PROPOSTA_COMPLETA")
        self.assertEqual((p["taxa"], p["condicoes"]["codCargo"]), ("0.0300", 100))
        self.assertIn("3,00%", p["explicacao"])
        self.assertIn("'taxa': Decimal('0.0300')", p["codigoPython"])
        self.assertEqual([e["ferramenta"] for e in corpo["trilhaFerramentas"]],
                         ["resolver_publico", "consultar_regras_concorrentes"])
        self.assertEqual(spring.chamou("/bases"), [])  # taxa absoluta não consulta a base

    def test_fluxo_2_ajuste_sobre_base_em_versao_existente(self):
        spring = SpringFalso()
        corpo = self._interpretar_ajuste_versao_existente(spring)
        p = corpo["propostas"][0]
        self.assertEqual(corpo["status"], "PROPOSTA_COMPLETA", p["pendencias"])
        self.assertEqual(p["taxa"], "0.0350")
        self.assertEqual(p["operacao"], {"tipo": "ADICIONAR_PP", "valor": "0.0100"})
        self.assertEqual(spring.chamou("/bases")[0], {"codMarca": "10", "codCargo": "100", "competencia": "2026-12"})
        self.assertEqual(spring.chamou("/regras-concorrentes")[0]["ignorarCampanhaId"], "camp-1")
        self.assertIn("Base de comissão consultada (marca 10, cargo 100, competência 2026-12): 2,50%", p["explicacao"])
        self.assertEqual(corpo["contexto"]["origem"], "VERSAO_EXISTENTE")
        # a IA não devolve ativação, publicação de versão nem identificadores financeiros
        self.assertFalse(_CAMPOS_DE_CONTROLE & (set(p) | set(p["condicoes"])))

    def test_fluxo_3_reinterpretacao_localizada(self):
        spring = SpringFalso()
        bloco = self._interpretar_ajuste_versao_existente(spring)["propostas"][0]
        outro = {**bloco, "idLocal": "p2", "condicoes": {"codLoja": 75}, "explicacao": "x", "codigoPython": None}

        self._usar([{"trecho_origem": "mais 2 pontos percentuais", "operacao_raw": "mais 2 pontos percentuais"}], spring)
        r = self.client.post("/api/v2/reinterpretar", json={
            "contexto": {"campanhaId": "camp-1", "revisao": 5, "origem": "VERSAO_EXISTENTE"},
            "idLocal": "p1",
            "textoAlterado": "mais 2 pontos percentuais",
            "blocoAtual": bloco,
            "demaisBlocos": [outro],
            "vigenciaCampanha": {"inicio": "2026-12-01", "fim": "2026-12-31"},
        })
        self.assertEqual(r.status_code, 200, r.text)
        corpo = r.json()
        nova = corpo["propostasSubstituicao"][0]
        self.assertEqual(nova["idLocal"], "p1")
        self.assertEqual((nova["condicoes"]["codCargo"], nova["condicoes"]["codMarca"]), (100, 10))  # herdados
        self.assertEqual(nova["taxa"], "0.0450")
        self.assertEqual(corpo["camposAlterados"], ["operacao", "taxa"])
        self.assertIn("herdada da vigência da campanha", nova["explicacao"])
        self.assertIn("'idLocal': 'p1'", nova["codigoPython"])
        self.assertEqual(spring.chamou("/regras-concorrentes")[-1]["ignorarCampanhaId"], "camp-1")
        self.assertEqual(outro["idLocal"], "p2")  # demais blocos não voltam na resposta
        self.assertNotIn("p2", json.dumps(corpo["propostasSubstituicao"]))

    def test_fluxo_4_atualizacao_de_artefatos_apos_edicao_manual(self):
        bloco = self._interpretar_ajuste_versao_existente(SpringFalso())["propostas"][0]
        bloco["taxa"] = "0.0500"
        r = self.client.post("/api/v2/atualizar-artefatos", json={
            "contexto": {"campanhaId": "camp-1", "revisao": 6, "origem": "VERSAO_EXISTENTE"},
            "bloco": bloco,
            "camposEditados": ["taxa"],
        })
        self.assertEqual(r.status_code, 200, r.text)
        novo = r.json()["bloco"]
        self.assertEqual(novo["taxa"], "0.0500")
        self.assertEqual(novo["operacao"], {"tipo": "TAXA_ABSOLUTA", "valor": "0.0500"})
        self.assertIn("5,00% definida manualmente pelo gestor (origem: MANUAL)", novo["explicacao"])
        self.assertNotIn("3,50%", novo["explicacao"])
        self.assertIn("Decimal('0.0500')", novo["codigoPython"])
        self.assertEqual(novo["condicoes"], bloco["condicoes"])

    def test_falha_da_base_preserva_o_obtido_sem_inventar_taxa(self):
        spring = SpringFalso(base={"erro": "indisponível"}, base_status=503)
        corpo = self._interpretar_ajuste_versao_existente(spring)
        p = corpo["propostas"][0]
        self.assertEqual(corpo["status"], "PROPOSTA_COM_PENDENCIAS")
        self.assertIsNone(p["taxa"])
        self.assertEqual((p["condicoes"]["codCargo"], p["condicoes"]["codMarca"]), (100, 10))
        codigos = {x["codigo"] for x in p["pendencias"]}
        self.assertIn("TOOL_FALHA", codigos)
        self.assertNotIn("BASE_AUSENTE", codigos)
        self.assertIn("a taxa final está pendente", p["explicacao"])
        self.assertFalse(any(r["fonte"] == "BASE_COMISS" for r in p["referencias"]))

    def test_base_ausente_vira_pendencia_objetiva(self):
        spring = SpringFalso(base={"encontrado": False})
        p = self._interpretar_ajuste_versao_existente(spring)["propostas"][0]
        self.assertIsNone(p["taxa"])
        pend = [x for x in p["pendencias"] if x["codigo"] == "BASE_AUSENTE"]
        self.assertEqual(len(pend), 1)
        self.assertTrue(pend[0]["pergunta"])
        # a pendência específica substitui o CAMPO_AUSENTE genérico da extração
        self.assertNotIn("CAMPO_AUSENTE", {x["codigo"] for x in p["pendencias"]})


if __name__ == "__main__":
    unittest.main()
