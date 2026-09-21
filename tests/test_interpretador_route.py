"""
Testes de integração para a rota de interpretação (Task S1-A08).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)

CONTEXTO_COM_CATALOGO = {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
        "marcas": {"10": "PRETO"},
        "cargos": {"100": "VENDEDOR LOJA"},
        "canais": ["ECOMMERCE"],
    },
}


class TestInterpretadorRoute(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_sucesso(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = {
            "canal": "ECOMMERCE",
            "taxa_raw": "5%",
            "vigencia_inicio_raw": "dezembro",
            "vigencia_fim_raw": "dezembro",
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        }
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Pagar 5% no canal ecommerce durante dezembro", "contexto": CONTEXTO_COM_CATALOGO},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["canal"], "ECOMMERCE")
        self.assertEqual(data["taxa"], "0.0500")
        self.assertEqual(data["pendencias"], [])

    def test_interpretar_texto_vazio_retorna_422(self):
        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "   ", "contexto": {}},
        )
        self.assertEqual(response.status_code, 422)

    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_erro_autenticacao_propaga_401(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMAuthenticationError("Chave inválida.")
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Pagar 5% no canal ecommerce", "contexto": {}},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error_code"], "LLM_AUTH_ERROR")

    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_erro_rate_limit_propaga_429(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMRateLimitError("Cota esgotada.")
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Pagar 5% no canal ecommerce", "contexto": {}},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error_code"], "LLM_RATE_LIMIT_ERROR")

    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_erro_timeout_propaga_504(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMTimeoutError("Tempo limite excedido.")
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Pagar 5% no canal ecommerce", "contexto": {}},
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error_code"], "LLM_TIMEOUT_ERROR")

    @patch("app.core.services.interpretador.time.sleep")
    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_erro_provider_propaga_502(self, mock_get_provider, mock_sleep):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMProviderError("Falha interna.")
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Pagar 5% no canal ecommerce", "contexto": {}},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error_code"], "LLM_PROVIDER_ERROR")

    @patch("app.core.services.interpretador.get_provider")
    def test_interpretar_com_pendencias_retorna_200(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = {
            "canal": None,
            "taxa_raw": None,
            "vigencia_inicio_raw": None,
            "vigencia_fim_raw": None,
            "criterios_nao_suportados": [],
            "ambiguidades_ou_duvidas": [],
            "marca_raw": None,
            "loja_raw": None,
            "cargo_raw": None,
        }
        mock_get_provider.return_value = mock_provider

        response = self.client.post(
            "/api/v1/interpretar",
            json={"texto": "Comissão para os bons vendedores", "contexto": {}},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(len(data["pendencias"]), 0)


if __name__ == "__main__":
    unittest.main()
