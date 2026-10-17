"""Testes das rotas v2: contrato, stubs 501 e erros no formato padrão."""

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


def agente_com(saida):
    provider = MagicMock()
    if isinstance(saida, Exception):
        provider.complete.side_effect = saida
    else:
        provider.complete.return_value = saida
    return AgenteInterpretador(provider, ToolRegistry())


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
        self.assertIsNone(corpo["propostas"][0]["explicacao"])  # IA-7
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

    def test_stubs_501_validam_payload(self):
        bloco = {"idLocal": "p1"}
        c = TestClient(app)
        r = c.post("/api/v2/reinterpretar", json={"idLocal": "p1", "textoAlterado": "4%", "blocoAtual": bloco})
        self.assertEqual((r.status_code, r.json()["error_code"]), (501, "NAO_IMPLEMENTADO"))
        r = c.post("/api/v2/atualizar-artefatos", json={"bloco": bloco, "camposEditados": ["taxa"]})
        self.assertEqual((r.status_code, r.json()["error_code"]), (501, "NAO_IMPLEMENTADO"))
        # payload inválido continua 422 (contrato validado)
        self.assertEqual(c.post("/api/v2/reinterpretar", json={}).status_code, 422)

    def test_openapi_expoe_rotas_v2(self):
        paths = TestClient(app).get("/openapi.json").json()["paths"]
        for rota in ("/api/v2/interpretar", "/api/v2/reinterpretar", "/api/v2/atualizar-artefatos"):
            self.assertIn(rota, paths)
        self.assertIn("/api/v1/interpretar", paths)  # v1 convive


if __name__ == "__main__":
    unittest.main()
