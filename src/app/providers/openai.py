"""
Provedor OpenAI.

SDK: openai
Variáveis de ambiente:
    LLM_PROVIDER=openai
    LLM_API_KEY=<sua-chave-openai>
    LLM_MODEL=gpt-4o-mini   (default)
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


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "SDK da OpenAI não instalado. Execute: pip install openai"
            ) from e

        if not settings.llm_api_key:
            raise LLMAuthenticationError(
                "Chave de API da OpenAI (LLM_API_KEY) não configurada no ambiente."
            )

        self._client = OpenAI(
            api_key=settings.llm_api_key,
            timeout=float(settings.llm_timeout_seconds),
        )
        self._model = settings.llm_model or "gpt-4o-mini"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama a OpenAI com saída estruturada via JSON Schema."""
        import openai

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_output_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "resposta_estruturada",
                        "schema": response_schema,
                        "strict": True,
                    },
                },
            )
        except openai.AuthenticationError:
            raise LLMAuthenticationError(
                "Credenciais inválidas ou não autorizadas para a OpenAI."
            ) from None
        except (openai.RateLimitError, openai.PermissionDeniedError):
            raise LLMRateLimitError(
                "Limite de requisições ou cota excedida na API da OpenAI."
            ) from None
        except (openai.APITimeoutError, TimeoutError):
            raise LLMTimeoutError(
                f"Tempo limite ({settings.llm_timeout_seconds}s) excedido ao comunicar com a OpenAI."
            ) from None
        except (openai.APIConnectionError, openai.InternalServerError, openai.APIStatusError):
            raise LLMProviderError(
                "Erro de comunicação ou indisponibilidade no serviço OpenAI."
            ) from None
        except Exception as e:
            if isinstance(e, (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
                raise e
            raise LLMProviderError(
                "Falha inesperada ao executar chamada à OpenAI."
            ) from None

        content = response.choices[0].message.content
        if not content:
            raise LLMResponseParsingError("A OpenAI retornou conteúdo vazio.")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            raise LLMResponseParsingError(
                "Falha ao decodificar JSON retornado pela OpenAI."
            ) from None
