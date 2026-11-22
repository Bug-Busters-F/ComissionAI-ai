"""Credencial interna usada nas ferramentas, sem chamadas externas."""
import os
import sys
import unittest
from unittest.mock import patch
import httpx
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from app.tools.client import BackendClient, BackendErro
from app.core.config import settings

class BackendAuthTest(unittest.TestCase):
    def test_envia_chave_em_get_e_post(self):
        vistos = []
        def handler(req):
            vistos.append(req)
            return httpx.Response(200, json={"encontrado": False})
        with patch.object(settings, "ai_service_api_key", "segredo-teste"):
            c = BackendClient(base_url="http://backend", transport=httpx.MockTransport(handler))
            c.get("/marcas")
            c.post("/regras-concorrentes", {})
        self.assertEqual(len(vistos), 2)
        for req in vistos:
            self.assertEqual(req.headers["X-Internal-Api-Key"], "segredo-teste")
            self.assertNotIn("Authorization", req.headers)
            self.assertTrue(req.url.path.startswith("/api/v1/consultas-ia/"))

    def test_cabecalho_configuravel(self):
        def handler(req):
            self.assertEqual(req.headers["X-Credencial-IA"], "teste")
            return httpx.Response(200, json={})
        with patch.object(settings, "ai_service_api_key", "teste"), patch.object(settings, "ai_service_auth_header", "X-Credencial-IA"):
            BackendClient(base_url="http://backend", transport=httpx.MockTransport(handler)).get("/marcas")

    def test_rejeicao_nao_vira_sem_dados_nem_retenta(self):
        vistos = []
        def handler(req):
            vistos.append(req)
            return httpx.Response(401, json={"message": "Sessão inválida"})
        c = BackendClient(base_url="http://backend", transport=httpx.MockTransport(handler))
        with self.assertRaises(BackendErro) as erro:
            c.get("/marcas")
        self.assertEqual(erro.exception.tipo, "HTTP_401")
        self.assertEqual(len(vistos), 1)

    def test_nao_encaminha_chave_em_redirecionamento(self):
        vistos = []
        def handler(req):
            vistos.append(req)
            return httpx.Response(307, headers={"Location": "http://outro-servico/"})
        with patch.object(settings, "ai_service_api_key", "teste"):
            c = BackendClient(base_url="http://backend", transport=httpx.MockTransport(handler))
            with self.assertRaises(BackendErro):
                c.get("/marcas")
        self.assertEqual(len(vistos), 1)
