"""Chamada ao provedor com uma única retentativa em falha transitória (mesma política do v1)."""

import logging
import time

from app.core.exceptions import LLMProviderError
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

RETRY_BACKOFF_SECONDS = 1.5


def completar_com_retry(provider: LLMProvider, prompt: str, schema: dict) -> dict:
    """Retenta só LLMProviderError (alta demanda); timeout, auth e rate limit propagam direto."""
    try:
        return provider.complete(prompt=prompt, response_schema=schema)
    except LLMProviderError as exc:
        logger.warning("Falha transitória do provedor (%s); retentando em %.1fs", exc.message, RETRY_BACKOFF_SECONDS)
        time.sleep(RETRY_BACKOFF_SECONDS)
        return provider.complete(prompt=prompt, response_schema=schema)
