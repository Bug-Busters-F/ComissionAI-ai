"""
Testes unitários para os provedores de LLM e factory (Task S1-A03).
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)
from app.providers import get_provider


class TestProviderFactory(unittest.TestCase):
    def test_provider_desconhecido_lanca_value_error(self):
        with patch("app.core.config.settings.llm_provider", "deepseek"):
            with self.assertRaises(ValueError) as ctx:
                get_provider()
            self.assertIn("desconhecido", str(ctx.exception).lower())

    def test_provider_gemini_sem_api_key_lanca_auth_error(self):
        with patch("app.core.config.settings.llm_provider", "gemini"):
            with patch("app.core.config.settings.llm_api_key", ""):
                fake_genai = types.ModuleType("google.generativeai")
                with patch.dict(sys.modules, {"google.generativeai": fake_genai}):
                    with self.assertRaises(LLMAuthenticationError):
                        get_provider()

    def test_provider_openai_sem_api_key_lanca_auth_error(self):
        with patch("app.core.config.settings.llm_provider", "openai"):
            with patch("app.core.config.settings.llm_api_key", ""):
                fake_openai = types.ModuleType("openai")
                fake_openai.OpenAI = MagicMock()
                with patch.dict(sys.modules, {"openai": fake_openai}):
                    with self.assertRaises(LLMAuthenticationError):
                        get_provider()

    def test_provider_anthropic_sem_api_key_lanca_auth_error(self):
        with patch("app.core.config.settings.llm_provider", "anthropic"):
            with patch("app.core.config.settings.llm_api_key", ""):
                fake_anthropic = types.ModuleType("anthropic")
                fake_anthropic.Anthropic = MagicMock()
                with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
                    with self.assertRaises(LLMAuthenticationError):
                        get_provider()


class TestGeminiProvider(unittest.TestCase):
    def setUp(self):
        self.fake_genai = types.ModuleType("google.generativeai")
        self.fake_genai.configure = MagicMock()
        self.fake_genai.GenerativeModel = MagicMock()
        self.fake_genai.GenerationConfig = MagicMock()

        self.fake_exceptions = types.ModuleType("google.api_core.exceptions")
        class GoogleAPIError(Exception): pass
        class GoogleAPICallError(GoogleAPIError): pass
        class Unauthenticated(GoogleAPICallError): pass
        class PermissionDenied(GoogleAPICallError): pass
        class ResourceExhausted(GoogleAPICallError): pass
        class TooManyRequests(GoogleAPICallError): pass
        class DeadlineExceeded(GoogleAPICallError): pass

        self.fake_exceptions.GoogleAPIError = GoogleAPIError
        self.fake_exceptions.GoogleAPICallError = GoogleAPICallError
        self.fake_exceptions.Unauthenticated = Unauthenticated
        self.fake_exceptions.PermissionDenied = PermissionDenied
        self.fake_exceptions.ResourceExhausted = ResourceExhausted
        self.fake_exceptions.TooManyRequests = TooManyRequests
        self.fake_exceptions.DeadlineExceeded = DeadlineExceeded

    def test_gemini_complete_sucesso(self):
        with patch.dict(sys.modules, {
            "google.generativeai": self.fake_genai,
            "google.api_core.exceptions": self.fake_exceptions,
        }):
            with patch("app.core.config.settings.llm_api_key", "fake-gemini-key"):
                from app.providers.gemini import GeminiProvider
                provider = GeminiProvider()

                mock_response = MagicMock()
                mock_response.text = '{"canal": "ECOMMERCE", "taxa": 0.05}'
                provider._model.generate_content.return_value = mock_response

                result = provider.complete("teste prompt", {})
                self.assertEqual(result, {"canal": "ECOMMERCE", "taxa": 0.05})

    def test_gemini_unauthenticated_error(self):
        with patch.dict(sys.modules, {
            "google.generativeai": self.fake_genai,
            "google.api_core.exceptions": self.fake_exceptions,
        }):
            with patch("app.core.config.settings.llm_api_key", "secret-key-123"):
                from app.providers.gemini import GeminiProvider
                provider = GeminiProvider()
                provider._model.generate_content.side_effect = self.fake_exceptions.Unauthenticated("Invalid API key")

                with self.assertRaises(LLMAuthenticationError) as ctx:
                    provider.complete("teste prompt", {})
                self.assertNotIn("secret-key-123", str(ctx.exception))

    def test_gemini_rate_limit_error(self):
        with patch.dict(sys.modules, {
            "google.generativeai": self.fake_genai,
            "google.api_core.exceptions": self.fake_exceptions,
        }):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider
                provider = GeminiProvider()
                provider._model.generate_content.side_effect = self.fake_exceptions.ResourceExhausted("Quota limit")

                with self.assertRaises(LLMRateLimitError):
                    provider.complete("teste prompt", {})

    def test_gemini_timeout_error(self):
        with patch.dict(sys.modules, {
            "google.generativeai": self.fake_genai,
            "google.api_core.exceptions": self.fake_exceptions,
        }):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider
                provider = GeminiProvider()
                provider._model.generate_content.side_effect = self.fake_exceptions.DeadlineExceeded("Deadline exceeded")

                with self.assertRaises(LLMTimeoutError):
                    provider.complete("teste prompt", {})

    def test_gemini_invalid_json_parsing_error(self):
        with patch.dict(sys.modules, {
            "google.generativeai": self.fake_genai,
            "google.api_core.exceptions": self.fake_exceptions,
        }):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider
                provider = GeminiProvider()
                mock_response = MagicMock()
                mock_response.text = "invalid json string"
                provider._model.generate_content.return_value = mock_response

                with self.assertRaises(LLMResponseParsingError):
                    provider.complete("teste prompt", {})


class TestOpenAIProvider(unittest.TestCase):
    def setUp(self):
        self.fake_openai = types.ModuleType("openai")
        class OpenAIError(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__(*args)
        class AuthenticationError(OpenAIError): pass
        class RateLimitError(OpenAIError): pass
        class APITimeoutError(OpenAIError): pass
        class APIConnectionError(OpenAIError): pass
        class InternalServerError(OpenAIError): pass
        class APIStatusError(OpenAIError): pass
        class PermissionDeniedError(OpenAIError): pass

        self.fake_openai.OpenAI = MagicMock()
        self.fake_openai.OpenAIError = OpenAIError
        self.fake_openai.AuthenticationError = AuthenticationError
        self.fake_openai.RateLimitError = RateLimitError
        self.fake_openai.APITimeoutError = APITimeoutError
        self.fake_openai.APIConnectionError = APIConnectionError
        self.fake_openai.InternalServerError = InternalServerError
        self.fake_openai.APIStatusError = APIStatusError
        self.fake_openai.PermissionDeniedError = PermissionDeniedError

    def test_openai_complete_sucesso(self):
        with patch.dict(sys.modules, {"openai": self.fake_openai}):
            with patch("app.core.config.settings.llm_api_key", "fake-openai-key"):
                from app.providers.openai import OpenAIProvider
                provider = OpenAIProvider()

                mock_choice = MagicMock()
                mock_choice.message.content = '{"canal": "LOJA_FISICA", "taxa": 0.03}'
                mock_res = MagicMock()
                mock_res.choices = [mock_choice]
                provider._client.chat.completions.create.return_value = mock_res

                result = provider.complete("teste prompt", {})
                self.assertEqual(result, {"canal": "LOJA_FISICA", "taxa": 0.03})

    def test_openai_auth_error(self):
        with patch.dict(sys.modules, {"openai": self.fake_openai}):
            with patch("app.core.config.settings.llm_api_key", "secret-openai-key"):
                from app.providers.openai import OpenAIProvider
                provider = OpenAIProvider()
                provider._client.chat.completions.create.side_effect = self.fake_openai.AuthenticationError("Invalid Auth")

                with self.assertRaises(LLMAuthenticationError) as ctx:
                    provider.complete("teste prompt", {})
                self.assertNotIn("secret-openai-key", str(ctx.exception))

    def test_openai_rate_limit_error(self):
        with patch.dict(sys.modules, {"openai": self.fake_openai}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.openai import OpenAIProvider
                provider = OpenAIProvider()
                provider._client.chat.completions.create.side_effect = self.fake_openai.RateLimitError("Quota exceeded")

                with self.assertRaises(LLMRateLimitError):
                    provider.complete("teste prompt", {})

    def test_openai_timeout_error(self):
        with patch.dict(sys.modules, {"openai": self.fake_openai}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.openai import OpenAIProvider
                provider = OpenAIProvider()
                provider._client.chat.completions.create.side_effect = self.fake_openai.APITimeoutError(request=MagicMock())

                with self.assertRaises(LLMTimeoutError):
                    provider.complete("teste prompt", {})


class TestAnthropicProvider(unittest.TestCase):
    def setUp(self):
        self.fake_anthropic = types.ModuleType("anthropic")
        class AnthropicError(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__(*args)
        class AuthenticationError(AnthropicError): pass
        class RateLimitError(AnthropicError): pass
        class APITimeoutError(AnthropicError): pass
        class APIConnectionError(AnthropicError): pass
        class InternalServerError(AnthropicError): pass
        class APIStatusError(AnthropicError): pass
        class PermissionDeniedError(AnthropicError): pass

        self.fake_anthropic.Anthropic = MagicMock()
        self.fake_anthropic.AnthropicError = AnthropicError
        self.fake_anthropic.AuthenticationError = AuthenticationError
        self.fake_anthropic.RateLimitError = RateLimitError
        self.fake_anthropic.APITimeoutError = APITimeoutError
        self.fake_anthropic.APIConnectionError = APIConnectionError
        self.fake_anthropic.InternalServerError = InternalServerError
        self.fake_anthropic.APIStatusError = APIStatusError
        self.fake_anthropic.PermissionDeniedError = PermissionDeniedError

    def test_anthropic_complete_sucesso(self):
        with patch.dict(sys.modules, {"anthropic": self.fake_anthropic}):
            with patch("app.core.config.settings.llm_api_key", "fake-anthropic-key"):
                from app.providers.anthropic import AnthropicProvider
                provider = AnthropicProvider()

                mock_block = MagicMock()
                mock_block.type = "tool_use"
                mock_block.input = {"canal": "WHATSAPP", "taxa": 0.04}

                mock_res = MagicMock()
                mock_res.content = [mock_block]
                provider._client.messages.create.return_value = mock_res

                result = provider.complete("teste prompt", {})
                self.assertEqual(result, {"canal": "WHATSAPP", "taxa": 0.04})

    def test_anthropic_auth_error(self):
        with patch.dict(sys.modules, {"anthropic": self.fake_anthropic}):
            with patch("app.core.config.settings.llm_api_key", "secret-anthropic-key"):
                from app.providers.anthropic import AnthropicProvider
                provider = AnthropicProvider()
                provider._client.messages.create.side_effect = self.fake_anthropic.AuthenticationError("Auth failed")

                with self.assertRaises(LLMAuthenticationError) as ctx:
                    provider.complete("teste prompt", {})
                self.assertNotIn("secret-anthropic-key", str(ctx.exception))

    def test_anthropic_missing_tool_block_error(self):
        with patch.dict(sys.modules, {"anthropic": self.fake_anthropic}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.anthropic import AnthropicProvider
                provider = AnthropicProvider()

                mock_res = MagicMock()
                mock_res.content = []
                provider._client.messages.create.return_value = mock_res

                with self.assertRaises(LLMResponseParsingError):
                    provider.complete("teste prompt", {})


if __name__ == "__main__":
    unittest.main()
