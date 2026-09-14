"""
Testes unitários para a hierarquia de exceções de domínio do LLM (Task S1-A03).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.exceptions import (
    LLMAuthenticationError,
    LLMBaseException,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)


class TestLLMExceptions(unittest.TestCase):
    def test_llm_base_exception(self):
        exc = LLMBaseException("Erro genérico", status_code=500, error_code="CUSTOM_CODE")
        self.assertEqual(exc.message, "Erro genérico")
        self.assertEqual(exc.status_code, 500)
        self.assertEqual(exc.error_code, "CUSTOM_CODE")
        self.assertEqual(str(exc), "Erro genérico")

    def test_llm_auth_error(self):
        exc = LLMAuthenticationError()
        self.assertEqual(exc.status_code, 401)
        self.assertEqual(exc.error_code, "LLM_AUTH_ERROR")
        self.assertIn("autenticação", exc.message.lower())

    def test_llm_rate_limit_error(self):
        exc = LLMRateLimitError()
        self.assertEqual(exc.status_code, 429)
        self.assertEqual(exc.error_code, "LLM_RATE_LIMIT_ERROR")
        self.assertIn("cota", exc.message.lower())

    def test_llm_timeout_error(self):
        exc = LLMTimeoutError()
        self.assertEqual(exc.status_code, 504)
        self.assertEqual(exc.error_code, "LLM_TIMEOUT_ERROR")
        self.assertIn("tempo limite", exc.message.lower())

    def test_llm_provider_error(self):
        exc = LLMProviderError()
        self.assertEqual(exc.status_code, 502)
        self.assertEqual(exc.error_code, "LLM_PROVIDER_ERROR")
        self.assertIn("interno", exc.message.lower())

    def test_llm_response_parsing_error(self):
        exc = LLMResponseParsingError()
        self.assertEqual(exc.status_code, 502)
        self.assertEqual(exc.error_code, "LLM_PARSING_ERROR")


if __name__ == "__main__":
    unittest.main()
