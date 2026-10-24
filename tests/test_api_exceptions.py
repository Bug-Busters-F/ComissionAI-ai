"""
Testes de integração para os handlers de exceção do FastAPI (Task S1-A03).
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderError,
)

# Rota temporária de teste para simular lançamentos de erro
@app.get("/test/error/auth")
def trigger_auth_error():
    raise LLMAuthenticationError("Chave inválida para o provedor.")

@app.get("/test/error/rate-limit")
def trigger_rate_limit_error():
    raise LLMRateLimitError("Cota esgotada.")

@app.get("/test/error/timeout")
def trigger_timeout_error():
    raise LLMTimeoutError("Tempo limite excedido.")

@app.get("/test/error/provider")
def trigger_provider_error():
    raise LLMProviderError("Falha interna no serviço de LLM.")

@app.get("/test/error/unexpected")
def trigger_unexpected_error():
    raise RuntimeError("Bug não previsto, não relacionado a LLM.")


@app.get("/test/error/rate-limit-retry")
def trigger_rate_limit_with_retry():
    raise LLMRateLimitError("Aguarde liberação da cota.", retry_after_seconds=2.1)


class TestAPIExceptionHandlers(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_auth_error_status_401(self):
        response = self.client.get("/test/error/auth")
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["error_code"], "LLM_AUTH_ERROR")
        self.assertIn("Chave inválida", data["detail"])

    def test_rate_limit_status_429(self):
        response = self.client.get("/test/error/rate-limit")
        self.assertEqual(response.status_code, 429)
        data = response.json()
        self.assertEqual(data["error_code"], "LLM_RATE_LIMIT_ERROR")
        self.assertIn("Cota esgotada", data["detail"])

    def test_rate_limit_mantem_cabecalho_retry_after_sem_alterar_corpo(self):
        response = self.client.get("/test/error/rate-limit-retry")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "3")
        self.assertEqual(response.json(), {"detail": "Aguarde liberação da cota.", "error_code": "LLM_RATE_LIMIT_ERROR"})

    def test_rate_limit_sem_prazo_nao_inventa_retry_after(self):
        response = self.client.get("/test/error/rate-limit")
        self.assertNotIn("retry-after", response.headers)

    def test_timeout_status_504(self):
        response = self.client.get("/test/error/timeout")
        self.assertEqual(response.status_code, 504)
        data = response.json()
        self.assertEqual(data["error_code"], "LLM_TIMEOUT_ERROR")
        self.assertIn("Tempo limite", data["detail"])

    def test_provider_error_status_502(self):
        response = self.client.get("/test/error/provider")
        self.assertEqual(response.status_code, 502)
        data = response.json()
        self.assertEqual(data["error_code"], "LLM_PROVIDER_ERROR")
        self.assertIn("Falha interna", data["detail"])

    def test_unexpected_exception_status_500_sem_vazar_detalhe_interno(self):
        # raise_server_exceptions=False: queremos a resposta HTTP do handler,
        # não a exceção Python subindo direto no teste.
        client_sem_raise = TestClient(app, raise_server_exceptions=False)

        response = client_sem_raise.get("/test/error/unexpected")

        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data["error_code"], "INTERNAL_ERROR")
        self.assertNotIn("Bug não previsto", data["detail"])
        self.assertNotIn("RuntimeError", data["detail"])


if __name__ == "__main__":
    unittest.main()
