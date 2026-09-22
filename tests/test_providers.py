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
                fake_genai = types.ModuleType("google.genai")
                fake_google = types.ModuleType("google")
                fake_google.genai = fake_genai
                with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
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

    def test_provider_groq_sem_api_key_lanca_auth_error(self):
        with patch("app.core.config.settings.llm_provider", "groq"):
            with patch("app.core.config.settings.llm_api_key", ""):
                fake_groq = types.ModuleType("groq")
                fake_groq.Groq = MagicMock()
                with patch.dict(sys.modules, {"groq": fake_groq}):
                    with self.assertRaises(LLMAuthenticationError):
                        get_provider()


class TestGeminiProvider(unittest.TestCase):
    def setUp(self):
        self.fake_genai = types.ModuleType("google.genai")
        self.fake_genai.Client = MagicMock()
        self.fake_types = types.ModuleType("google.genai.types")
        self.fake_types.GenerateContentConfig = MagicMock()
        self.fake_types.HttpOptions = MagicMock()

        self.fake_errors = types.ModuleType("google.genai.errors")

        class APIError(Exception):
            def __init__(self, code=0, response_json=None, response=None):
                self.code = code
                self.message = (
                    response_json.get("error", {}).get("message", "")
                    if isinstance(response_json, dict)
                    else str(response_json)
                )
                super().__init__(self.message)

        class ClientError(APIError):
            pass

        class ServerError(APIError):
            pass

        self.fake_errors.APIError = APIError
        self.fake_errors.ClientError = ClientError
        self.fake_errors.ServerError = ServerError

        self.fake_google = types.ModuleType("google")
        self.fake_google.genai = self.fake_genai

    def test_gemini_complete_sucesso(self):
        with patch.dict(
            sys.modules,
            {
                "google": self.fake_google,
                "google.genai": self.fake_genai,
                "google.genai.types": self.fake_types,
                "google.genai.errors": self.fake_errors,
            },
        ):
            with patch("app.core.config.settings.llm_api_key", "fake-gemini-key"):
                from app.providers.gemini import GeminiProvider

                provider = GeminiProvider()

                mock_response = MagicMock()
                mock_response.text = '{"canal": "ECOMMERCE", "taxa": 0.05}'
                provider._client.models.generate_content.return_value = mock_response

                result = provider.complete("teste prompt", {})
                self.assertEqual(result, {"canal": "ECOMMERCE", "taxa": 0.05})

    def test_gemini_unauthenticated_error(self):
        with patch.dict(
            sys.modules,
            {
                "google": self.fake_google,
                "google.genai": self.fake_genai,
                "google.genai.types": self.fake_types,
                "google.genai.errors": self.fake_errors,
            },
        ):
            with patch("app.core.config.settings.llm_api_key", "secret-key-123"):
                from app.providers.gemini import GeminiProvider

                provider = GeminiProvider()
                provider._client.models.generate_content.side_effect = self.fake_errors.ClientError(
                    401, {"error": {"message": "Invalid API key"}}
                )

                with self.assertRaises(LLMAuthenticationError) as ctx:
                    provider.complete("teste prompt", {})
                self.assertNotIn("secret-key-123", str(ctx.exception))

    def test_gemini_rate_limit_error(self):
        with patch.dict(
            sys.modules,
            {
                "google": self.fake_google,
                "google.genai": self.fake_genai,
                "google.genai.types": self.fake_types,
                "google.genai.errors": self.fake_errors,
            },
        ):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider

                provider = GeminiProvider()
                provider._client.models.generate_content.side_effect = self.fake_errors.ClientError(
                    429, {"error": {"message": "Quota limit exceeded"}}
                )

                with self.assertRaises(LLMRateLimitError):
                    provider.complete("teste prompt", {})

    def test_gemini_timeout_error(self):
        with patch.dict(
            sys.modules,
            {
                "google": self.fake_google,
                "google.genai": self.fake_genai,
                "google.genai.types": self.fake_types,
                "google.genai.errors": self.fake_errors,
            },
        ):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider

                provider = GeminiProvider()
                provider._client.models.generate_content.side_effect = TimeoutError(
                    "Deadline exceeded"
                )

                with self.assertRaises(LLMTimeoutError):
                    provider.complete("teste prompt", {})

    def test_gemini_invalid_json_parsing_error(self):
        with patch.dict(
            sys.modules,
            {
                "google": self.fake_google,
                "google.genai": self.fake_genai,
                "google.genai.types": self.fake_types,
                "google.genai.errors": self.fake_errors,
            },
        ):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.gemini import GeminiProvider

                provider = GeminiProvider()
                mock_response = MagicMock()
                mock_response.text = "invalid json string"
                provider._client.models.generate_content.return_value = mock_response

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


class TestGroqProvider(unittest.TestCase):
    def setUp(self):
        self.fake_groq = types.ModuleType("groq")

        class GroqError(Exception):
            def __init__(self, *args, **kwargs):
                super().__init__(*args)

        class AuthenticationError(GroqError): pass
        class RateLimitError(GroqError): pass
        class APITimeoutError(GroqError): pass
        class APIConnectionError(GroqError): pass
        class InternalServerError(GroqError): pass
        class APIStatusError(GroqError): pass
        class PermissionDeniedError(GroqError): pass

        self.fake_groq.Groq = MagicMock()
        self.fake_groq.GroqError = GroqError
        self.fake_groq.AuthenticationError = AuthenticationError
        self.fake_groq.RateLimitError = RateLimitError
        self.fake_groq.APITimeoutError = APITimeoutError
        self.fake_groq.APIConnectionError = APIConnectionError
        self.fake_groq.InternalServerError = InternalServerError
        self.fake_groq.APIStatusError = APIStatusError
        self.fake_groq.PermissionDeniedError = PermissionDeniedError

    def test_groq_complete_sucesso(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "fake-groq-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()

                mock_choice = MagicMock()
                mock_choice.message.content = '{"canal": "ECOMMERCE", "taxa": 0.05}'
                mock_res = MagicMock()
                mock_res.choices = [mock_choice]
                provider._client.chat.completions.create.return_value = mock_res

                result = provider.complete("teste prompt", {})
                self.assertEqual(result, {"canal": "ECOMMERCE", "taxa": 0.05})

    def test_groq_auth_error(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "secret-groq-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()
                provider._client.chat.completions.create.side_effect = self.fake_groq.AuthenticationError("Invalid Auth")

                with self.assertRaises(LLMAuthenticationError) as ctx:
                    provider.complete("teste prompt", {})
                self.assertNotIn("secret-groq-key", str(ctx.exception))

    def test_groq_rate_limit_error(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()
                provider._client.chat.completions.create.side_effect = self.fake_groq.RateLimitError("Rate limit reached")

                with self.assertRaises(LLMRateLimitError):
                    provider.complete("teste prompt", {})

    def test_groq_timeout_error(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()
                provider._client.chat.completions.create.side_effect = self.fake_groq.APITimeoutError(request=MagicMock())

                with self.assertRaises(LLMTimeoutError):
                    provider.complete("teste prompt", {})

    def test_groq_empty_content_parsing_error(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()
                mock_choice = MagicMock()
                mock_choice.message.content = ""
                mock_res = MagicMock()
                mock_res.choices = [mock_choice]
                provider._client.chat.completions.create.return_value = mock_res

                with self.assertRaises(LLMResponseParsingError):
                    provider.complete("teste prompt", {})

    def test_groq_invalid_json_parsing_error(self):
        with patch.dict(sys.modules, {"groq": self.fake_groq}):
            with patch("app.core.config.settings.llm_api_key", "fake-key"):
                from app.providers.groq import GroqProvider
                provider = GroqProvider()
                mock_choice = MagicMock()
                mock_choice.message.content = "not json"
                mock_res = MagicMock()
                mock_res.choices = [mock_choice]
                provider._client.chat.completions.create.return_value = mock_res

                with self.assertRaises(LLMResponseParsingError):
                    provider.complete("teste prompt", {})


if __name__ == "__main__":
    unittest.main()
