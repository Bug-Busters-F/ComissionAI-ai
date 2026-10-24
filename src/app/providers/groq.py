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
import logging
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from app.core.config import settings
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)


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

    # Modelos aninhados do Pydantic ficam em $defs (ex.: RegraRawLLM dentro da extração)
    for chave in ("$defs", "definitions"):
        if chave in s:
            s[chave] = {nome: _preparar_schema_estrito(sub) for nome, sub in s[chave].items()}

    return s


def _retry_after_seconds(exc: Exception) -> float | None:
    """Só um cabeçalho permitido é lido; corpo da falha/credenciais não são expostos."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


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

        self._timeout = float(settings.llm_timeout_seconds)
        # Evita as retentativas internas do SDK para que uma falha de conexão
        # possa acionar o fallback IPv4 antes do timeout do Spring.
        self._client = Groq(
            api_key=settings.llm_api_key,
            timeout=httpx.Timeout(self._timeout, connect=min(3.0, self._timeout)),
            max_retries=0,
        )
        self._model = settings.llm_model or "openai/gpt-oss-20b"

    def _request_payload(self, prompt: str, schema: dict) -> dict:
        return {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "resposta_estruturada",
                    "schema": schema,
                    "strict": True,
                },
            },
        }

    def _complete_ipv4(self, payload: dict):
        """Repete uma chamada de transporte usando somente IPv4.

        O transporte padrão continua sendo a primeira tentativa. O cliente
        temporário limita o fallback a esta chamada e mantém TLS, DNS e a
        validação normal do SDK.
        """
        import groq

        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport)
        try:
            ipv4_client = groq.Groq(
                api_key=settings.llm_api_key,
                timeout=httpx.Timeout(self._timeout, connect=min(3.0, self._timeout)),
                max_retries=0,
                http_client=http_client,
            )
            try:
                return ipv4_client.chat.completions.create(**payload)
            finally:
                close = getattr(ipv4_client, "close", None)
                if callable(close):
                    close()
        finally:
            http_client.close()

    def _complete_with_ipv4_fallback(self, payload: dict):
        import groq

        started_at = time.monotonic()
        try:
            return self._client.chat.completions.create(**payload)
        except (groq.APIConnectionError, groq.APITimeoutError, TimeoutError) as primary_error:
            elapsed = time.monotonic() - started_at
            logger.warning(
                "Falha de conexão com a Groq após %.2fs; tentando uma vez via IPv4.",
                elapsed,
            )
            try:
                timeout = payload.get("timeout")
                if isinstance(timeout, httpx.Timeout):
                    remaining = timeout.read - elapsed
                    if remaining <= 0:
                        raise primary_error
                    payload = {**payload, "timeout": httpx.Timeout(remaining, connect=min(3.0, remaining))}
                return self._complete_ipv4(payload)
            except (groq.APIConnectionError, groq.APITimeoutError, TimeoutError):
                # Mantém o erro original para que o tratamento existente
                # classifique a causa sem expor detalhes da chave ou do prompt.
                raise primary_error from None

    def _complete_with_rate_limit_retry(self, payload: dict):
        import groq

        deadline = time.monotonic() + self._timeout
        for attempt in range(settings.llm_rate_limit_max_retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMTimeoutError("Tempo limite excedido ao aguardar liberação da Groq.")
            request = {**payload, "timeout": httpx.Timeout(remaining, connect=min(3.0, remaining))}
            try:
                return self._complete_with_ipv4_fallback(request)
            except groq.RateLimitError as exc:
                delay = _retry_after_seconds(exc)
                remaining = deadline - time.monotonic()
                if (
                    attempt >= settings.llm_rate_limit_max_retries
                    or delay is None
                    or delay > settings.llm_rate_limit_max_wait_seconds
                    or delay >= remaining
                ):
                    raise
                logger.warning("Limite da Groq atingido; nova tentativa em %.2fs (tentativa %s).", delay, attempt + 1)
                time.sleep(delay)

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama a Groq com saída estruturada via JSON Schema estrito."""
        import groq

        schema_estrito = _preparar_schema_estrito(response_schema)

        try:
            response = self._complete_with_rate_limit_retry(
                self._request_payload(prompt, schema_estrito)
            )
        except groq.AuthenticationError:
            raise LLMAuthenticationError(
                "Credenciais inválidas ou não autorizadas para a Groq."
            ) from None
        except groq.RateLimitError as exc:
            delay = _retry_after_seconds(exc)
            message = "Limite de requisições ou cota excedida na API da Groq."
            if delay is not None:
                message += f" Tente novamente em {math.ceil(delay)} segundo(s)."
            raise LLMRateLimitError(message, retry_after_seconds=delay) from None
        except groq.PermissionDeniedError:
            raise LLMAuthenticationError("Acesso ao modelo não autorizado na Groq.") from None
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
