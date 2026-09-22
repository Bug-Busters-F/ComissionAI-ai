"""
Provedor Groq.

SDK: groq
Variáveis de ambiente:
    LLM_PROVIDER=groq
    LLM_API_KEY=<sua-chave-groq>
    LLM_MODEL=openai/gpt-oss-20b   (default)

Nota sobre JSON Schema:
    A Groq API exige que todo objeto no schema enviado com
    response_format={"type": "json_schema"} contenha
    "additionalProperties": false explicitamente.
    O método _preparar_schema_estrito() aplica essa transformação
    recursivamente antes de cada chamada.
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


def _preparar_schema_estrito(schema: dict) -> dict:
    """
    Adapta um JSON Schema gerado pelo Pydantic para ser compatível com
    a Groq API no modo json_schema estrito.

    A Groq exige que todos os objetos do schema possuam
    `additionalProperties: false` e que todos os campos sejam listados
    em `required`. Esta função aplica essas regras recursivamente.
    """
    if not isinstance(schema, dict):
        return schema

    s = dict(schema)

    # Processa objetos (com properties)
    if s.get("type") == "object" or "properties" in s:
        s["type"] = "object"
        s["additionalProperties"] = False
        if "properties" in s:
            s["required"] = list(s["properties"].keys())
            s["properties"] = {
                k: _preparar_schema_estrito(v)
                for k, v in s["properties"].items()
            }

    # Processa arrays (items podem ser objetos)
    if "items" in s:
        s["items"] = _preparar_schema_estrito(s["items"])

    # Processa anyOf / oneOf / allOf
    for chave in ("anyOf", "oneOf", "allOf"):
        if chave in s:
            s[chave] = [_preparar_schema_estrito(sub) for sub in s[chave]]

    return s


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            from groq import Groq
        except ImportError as e:
            raise ImportError(
                "SDK da Groq não instalado. Execute: pip install groq"
            ) from e

        if not settings.llm_api_key:
            raise LLMAuthenticationError(
                "Chave de API da Groq (LLM_API_KEY) não configurada no ambiente."
            )

        self._client = Groq(
            api_key=settings.llm_api_key,
            timeout=float(settings.llm_timeout_seconds),
        )
        self._model = settings.llm_model or "openai/gpt-oss-20b"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama a Groq com saída estruturada via JSON Schema estrito."""
        import groq

        schema_estrito = _preparar_schema_estrito(response_schema)

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
                        "schema": schema_estrito,
                        "strict": True,
                    },
                },
            )
        except groq.AuthenticationError:
            raise LLMAuthenticationError(
                "Credenciais inválidas ou não autorizadas para a Groq."
            ) from None
        except (groq.RateLimitError, groq.PermissionDeniedError):
            raise LLMRateLimitError(
                "Limite de requisições ou cota excedida na API da Groq."
            ) from None
        except (groq.APITimeoutError, TimeoutError):
            raise LLMTimeoutError(
                f"Tempo limite ({settings.llm_timeout_seconds}s) excedido ao comunicar com a Groq."
            ) from None
        except groq.NotFoundError:
            raise LLMProviderError(
                f"Modelo '{self._model}' não encontrado ou sem acesso na conta Groq. "
                "Verifique o valor de LLM_MODEL no arquivo .env."
            ) from None
        except groq.BadRequestError as e:
            raise LLMProviderError(
                f"Requisição inválida para a API Groq: {e}"
            ) from None
        except (groq.APIConnectionError, groq.InternalServerError, groq.APIStatusError):
            raise LLMProviderError(
                "Erro de comunicação ou indisponibilidade no serviço Groq."
            ) from None
        except Exception as e:
            if isinstance(e, (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
                raise e
            raise LLMProviderError(
                "Falha inesperada ao executar chamada à Groq."
            ) from None

        content = response.choices[0].message.content
        if not content:
            raise LLMResponseParsingError("A Groq retornou conteúdo vazio.")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            raise LLMResponseParsingError(
                "Falha ao decodificar JSON retornado pela Groq."
            ) from None
