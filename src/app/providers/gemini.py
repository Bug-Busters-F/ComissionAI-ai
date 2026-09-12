"""
Provedor Google Gemini.

SDK: google-generativeai
Variáveis de ambiente:
    LLM_PROVIDER=gemini
    LLM_API_KEY=<sua-chave-gemini>
    LLM_MODEL=gemini-1.5-flash   (default)
"""

import json
from app.core.config import settings
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)
from app.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "SDK do Gemini não instalado. Execute: pip install google-generativeai"
            ) from e

        if not settings.llm_api_key:
            raise LLMAuthenticationError(
                "Chave de API do Gemini (LLM_API_KEY) não configurada no ambiente."
            )

        genai.configure(api_key=settings.llm_api_key)
        self._model_name = settings.llm_model or "gemini-1.5-flash"
        self._model = genai.GenerativeModel(self._model_name)

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama o Gemini com saída estruturada via response_schema."""
        import google.generativeai as genai
        from google.api_core import exceptions as google_exceptions

        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
        )

        try:
            response = self._model.generate_content(
                prompt,
                generation_config=generation_config,
                request_options={"timeout": settings.llm_timeout_seconds},
            )
        except (
            google_exceptions.Unauthenticated,
            google_exceptions.PermissionDenied,
        ) as e:
            raise LLMAuthenticationError(
                "Credenciais inválidas ou não autorizadas para o Google Gemini."
            ) from None
        except (
            google_exceptions.ResourceExhausted,
            google_exceptions.TooManyRequests,
        ) as e:
            raise LLMRateLimitError(
                "Limite de requisições ou cota excedida na API do Google Gemini."
            ) from None
        except (google_exceptions.DeadlineExceeded, TimeoutError) as e:
            raise LLMTimeoutError(
                f"Tempo limite ({settings.llm_timeout_seconds}s) excedido ao comunicar com o Google Gemini."
            ) from None
        except (google_exceptions.GoogleAPICallError, google_exceptions.GoogleAPIError) as e:
            raise LLMProviderError(
                "Erro de comunicação com o serviço Google Gemini."
            ) from None
        except Exception as e:
            if isinstance(e, (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
                raise e
            # Tratar possíveis mensagens de erro genéricas que indiquem problemas de auth/quota
            err_msg = str(e).lower()
            if "api key" in err_msg or "unauthenticated" in err_msg or "permission" in err_msg:
                raise LLMAuthenticationError(
                    "Credenciais inválidas para o Google Gemini."
                ) from None
            if "quota" in err_msg or "rate" in err_msg or "resource exhausted" in err_msg:
                raise LLMRateLimitError(
                    "Limite de cota excedido no Google Gemini."
                ) from None
            if "timeout" in err_msg or "deadline" in err_msg:
                raise LLMTimeoutError(
                    "Tempo limite excedido na chamada ao Google Gemini."
                ) from None
            raise LLMProviderError(
                "Falha inesperada ao executar chamada ao Google Gemini."
            ) from None

        if not response.text:
            raise LLMResponseParsingError("O modelo Gemini retornou uma resposta vazia.")

        try:
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            raise LLMResponseParsingError(
                "Falha ao decodificar JSON retornado pelo Google Gemini."
            ) from None
