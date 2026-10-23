"""Testes das rotas v2: contrato, reinterpretação, artefatos e erros no formato padrão."""

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from app.api.routes.v2 import get_agente
from app.core.agente import AgenteInterpretador
from app.core.exceptions import LLMAuthenticationError
from app.main import app
from app.tools.base import ToolRegistry

EXTRACAO = {
    "regras": [{"trecho_origem": "3% para vendedores", "taxa_raw": "3%", "canal": "ECOMMERCE"}],
    "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro",
}


from app.core.agente.hooks import HooksAjusteSobreBase


def agente_com(saida):
    provider = MagicMock()
    if isinstance(saida, Exception):
        provider.complete.side_effect = saida
    else:
        provider.complete.return_value = saida
    return AgenteInterpretador(provider, ToolRegistry(), hooks=HooksAjusteSobreBase())


class TestRotasV2(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_interpretar_devolve_lista(self):
        app.dependency_overrides[get_agente] = lambda: agente_com(EXTRACAO)
        r = TestClient(app).post("/api/v2/interpretar", json={
            "texto": "3% para vendedores em dezembro", "dataReferencia": "2026-09-07",
            "contexto": {"campanhaId": "c1", "revisao": 3}})
        self.assertEqual(r.status_code, 200)
        corpo = r.json()
        self.assertEqual(len(corpo["propostas"]), 1)
        self.assertEqual(corpo["contexto"], {"campanhaId": "c1", "revisao": 3, "origem": "NOVA", "substituiVersao": None})
        self.assertEqual(corpo["propostas"][0]["taxa"], "0.0300")
        self.assertEqual(corpo["propostas"][0]["origem"]["trecho"], "3% para vendedores")
        self.assertIsNotNone(corpo["propostas"][0]["explicacao"])  # IA-7 implementado
        self.assertIsNotNone(corpo["propostas"][0]["codigoPython"])  # IA-7 implementado
        self.assertIn(corpo["status"], ("PROPOSTA_COMPLETA", "PROPOSTA_COM_PENDENCIAS"))

    def test_texto_vazio_422(self):
        app.dependency_overrides[get_agente] = lambda: agente_com(EXTRACAO)
        r = TestClient(app).post("/api/v2/interpretar", json={"texto": "   "})
        self.assertEqual(r.status_code, 422)

    def test_erro_de_llm_mantem_formato(self):
        app.dependency_overrides[get_agente] = lambda: agente_com(LLMAuthenticationError())
        r = TestClient(app).post("/api/v2/interpretar", json={"texto": "3% para vendedores"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error_code"], "LLM_AUTH_ERROR")

    def test_reinterpretar_retorna_200_e_substitui_bloco(self):
        # Reinterpretação que divide em 2 blocos
        saida_llm = {
            "regras": [
                {"trecho_origem": "2% loja 75", "taxa_raw": "2%", "loja_raw": "75"},
                {"trecho_origem": "4% ecommerce", "taxa_raw": "4%", "canal": "ECOMMERCE"},
            ],
            "vigencia_inicio_raw": "2026-12-01",
            "vigencia_fim_raw": "2026-12-31",
        }
        app.dependency_overrides[get_agente] = lambda: agente_com(saida_llm)
        bloco = {"idLocal": "p1", "taxa": "0.0300"}
        c = TestClient(app)
        r = c.post(
            "/api/v2/reinterpretar",
            json={
                "idLocal": "p1",
                "textoAlterado": "2% para loja 75 e 4% para ecommerce",
                "blocoAtual": bloco,
                "demaisBlocos": [{"idLocal": "p2", "taxa": "0.0500"}],
            },
        )
        self.assertEqual(r.status_code, 200)
        corpo = r.json()
        self.assertEqual(len(corpo["propostasSubstituicao"]), 2)
        # Primeiro bloco preserva idLocal original; segundo recebe sufixo
        self.assertEqual(corpo["propostasSubstituicao"][0]["idLocal"], "p1")
        self.assertEqual(corpo["propostasSubstituicao"][1]["idLocal"], "p1_2")
        self.assertIn("taxa", corpo["camposAlterados"])

    def test_atualizar_artefatos_taxa_manual_explicacao_coerente(self):
        bloco = {
            "idLocal": "p1",
            "taxa": "0.0450",
            "condicoes": {"codCargo": 100, "descriCargo": "VENDEDOR"},
        }
        c = TestClient(app)
        r = c.post(
            "/api/v2/atualizar-artefatos",
            json={
                "bloco": bloco,
                "camposEditados": ["taxa"],
                "origemCampos": {"taxa": "MANUAL"},
            },
        )
        self.assertEqual(r.status_code, 200)
        corpo = r.json()
        bloco_res = corpo["bloco"]
        self.assertEqual(bloco_res["taxa"], "0.0450")
        self.assertIn("MANUAL", bloco_res["explicacao"])
        self.assertIsNotNone(bloco_res["codigoPython"])

    def test_payload_invalido_reinterpretar_422(self):
        c = TestClient(app)
        self.assertEqual(c.post("/api/v2/reinterpretar", json={}).status_code, 422)

    def test_openapi_expoe_rotas_v2(self):
        paths = TestClient(app).get("/openapi.json").json()["paths"]
        for rota in ("/api/v2/interpretar", "/api/v2/reinterpretar", "/api/v2/atualizar-artefatos"):
            self.assertIn(rota, paths)
        self.assertIn("/api/v1/interpretar", paths)  # v1 convive


if __name__ == "__main__":
    unittest.main()
