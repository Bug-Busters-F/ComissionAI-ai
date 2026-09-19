"""
Provedor Google Gemini.

SDK: google-genai (pacote oficial google-genai)
Variáveis de ambiente:
    LLM_PROVIDER=gemini
    LLM_API_KEY=<sua-chave-gemini>
    LLM_MODEL=gemini-3.6-flash   (default)
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


def _to_gemini_schema(schema_dict: dict) -> dict:
    """
    Converte um JSON Schema gerado pelo Pydantic para o formato aceito pelo SDK google-genai.
    Remove campos incompatíveis (ex: 'example', 'default', 'title') e converte 'anyOf' em 'nullable'.
    """
    if not isinstance(schema_dict, dict):
        return schema_dict

    result = {}
    if "type" in schema_dict:
        result["type"] = schema_dict["type"].upper()
    elif "anyOf" in schema_dict:
        # Trata campos opcionais do Pydantic: anyOf: [{'type': 'string'}, {'type': 'null'}]
        valid_types = [
            x for x in schema_dict["anyOf"] if isinstance(x, dict) and x.get("type") != "null"
        ]
        if valid_types:
            result.update(_to_gemini_schema(valid_types[0]))
        result["nullable"] = True

    if "description" in schema_dict:
        result["description"] = schema_dict["description"]
    if "nullable" in schema_dict:
        result["nullable"] = schema_dict["nullable"]
    if "enum" in schema_dict:
        result["enum"] = schema_dict["enum"]
    if "required" in schema_dict:
        result["required"] = schema_dict["required"]
    if "properties" in schema_dict and isinstance(schema_dict["properties"], dict):
        result["properties"] = {
            k: _to_gemini_schema(v) for k, v in schema_dict["properties"].items()
        }
    if "items" in schema_dict and isinstance(schema_dict["items"], dict):
        result["items"] = _to_gemini_schema(schema_dict["items"])
    return result


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            from google import genai
        except ImportError as e:
            raise ImportError(
                "SDK do Gemini não instalado. Execute: pip install google-genai"
            ) from e

        if not settings.llm_api_key:
            raise LLMAuthenticationError(
                "Chave de API do Gemini (LLM_API_KEY) não configurada no ambiente."
            )

        self._client = genai.Client(api_key=settings.llm_api_key)
        self._model_name = settings.llm_model or "gemini-3.6-flash"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama o Gemini com saída estruturada via response_schema usando o SDK google-genai."""
        try:
            from google.genai import errors as genai_errors
            from google.genai import types
        except ImportError as e:
            raise ImportError(
                "SDK do Gemini não instalado. Execute: pip install google-genai"
            ) from e

        gemini_schema = _to_gemini_schema(response_schema) if response_schema else None

        http_options = (
            types.HttpOptions(timeout=int(settings.llm_timeout_seconds * 1000))
            if settings.llm_timeout_seconds
            else None
        )

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=gemini_schema,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            http_options=http_options,
        )

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=config,
            )
        except genai_errors.ClientError as e:
            err_msg = (e.message or str(e)).lower()
            code = getattr(e, "code", None)
            if code in (401, 403) or "api_key" in err_msg or "unauthenticated" in err_msg or "permission" in err_msg:
                raise LLMAuthenticationError(
                    f"Credenciais inválidas ou não autorizadas para o Google Gemini: {e.message or e}"
                ) from None
            if code == 404 or "not found" in err_msg:
                raise LLMProviderError(
                    f"Modelo Gemini '{self._model_name}' não encontrado ou indisponível: {e.message or e}"
                ) from None
            if code == 429 or "quota" in err_msg or "rate" in err_msg or "resource_exhausted" in err_msg:
                raise LLMRateLimitError(
                    f"Limite de requisições ou cota excedida na API do Google Gemini: {e.message or e}"
                ) from None
            raise LLMProviderError(
                f"Erro de comunicação com o serviço Google Gemini: {e.message or e}"
            ) from None
        except genai_errors.APIError as e:
            err_msg = (e.message or str(e)).lower()
            code = getattr(e, "code", None)
            if code in (401, 403):
                raise LLMAuthenticationError(
                    f"Credenciais inválidas para o Google Gemini: {e.message or e}"
                ) from None
            if code == 429:
                raise LLMRateLimitError(
                    f"Limite de cota excedido no Google Gemini: {e.message or e}"
                ) from None
            if code in (408, 504) or "timeout" in err_msg or "deadline" in err_msg:
                raise LLMTimeoutError(
                    f"Tempo limite excedido na chamada ao Google Gemini: {e.message or e}"
                ) from None
            raise LLMProviderError(
                f"Erro de comunicação com o serviço Google Gemini: {e.message or e}"
            ) from None
        except TimeoutError as e:
            raise LLMTimeoutError(
                f"Tempo limite ({settings.llm_timeout_seconds}s) excedido ao comunicar com o Google Gemini."
            ) from None
        except Exception as e:
            if isinstance(e, (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
                raise e
            err_msg = str(e).lower()
            if "timeout" in err_msg or "deadline" in err_msg:
                raise LLMTimeoutError(
                    "Tempo limite excedido na chamada ao Google Gemini."
                ) from None
            if "api key" in err_msg or "unauthenticated" in err_msg or "permission" in err_msg:
                raise LLMAuthenticationError(
                    f"Credenciais inválidas para o Google Gemini: {e}"
                ) from None
            if "quota" in err_msg or "rate" in err_msg or "resource exhausted" in err_msg:
                raise LLMRateLimitError(
                    f"Limite de cota excedido no Google Gemini: {e}"
                ) from None
            raise LLMProviderError(
                f"Falha inesperada ao executar chamada ao Google Gemini: {e}"
            ) from None

        if not response or not response.text:
            raise LLMResponseParsingError("O modelo Gemini retornou uma resposta vazia.")

        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            raise LLMResponseParsingError(
                "Falha ao decodificar JSON retornado pelo Google Gemini."
            ) from None
