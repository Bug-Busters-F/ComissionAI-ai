"""
Cliente HTTP do backend Spring (única porta de saída das tools).

Distingue falha de infraestrutura (timeout, 5xx, JSON inválido) de resposta de
negócio. Faz no máximo 1 retry, apenas para falhas transitórias (timeout/5xx);
4xx de negócio não é retentado.
"""

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PREFIXO = "/api/v1/consultas-ia"


class BackendErro(Exception):
    def __init__(self, tipo: str, detalhe: str = "", tentativas: int = 1) -> None:
        super().__init__(f"{tipo}: {detalhe}")
        self.tipo = tipo
        self.detalhe = detalhe
        self.tentativas = tentativas


class BackendClient:
    RETRY_BACKOFF_SECONDS = 0.3

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=(base_url or settings.backend_base_url).rstrip("/"),
            timeout=timeout if timeout is not None else settings.tool_timeout_seconds,
            transport=transport,
        )

    def get(self, caminho: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._chamar("GET", caminho, params=_limpar(params))

    def post(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        return self._chamar("POST", caminho, json=corpo)

    def _chamar(self, metodo: str, caminho: str, **kw: Any) -> dict[str, Any]:
        ultimo: BackendErro | None = None
        for tentativa in (1, 2):
            inicio = time.monotonic()
            try:
                resp = self._client.request(metodo, PREFIXO + caminho, **kw)
            except httpx.TimeoutException as exc:
                ultimo = BackendErro("TIMEOUT", type(exc).__name__, tentativa)
            except httpx.HTTPError as exc:
                ultimo = BackendErro("INDISPONIVEL", type(exc).__name__, tentativa)
            else:
                logger.info(
                    "backend %s %s -> %s (%.0fms)",
                    metodo, caminho, resp.status_code, (time.monotonic() - inicio) * 1000,
                )
                if resp.status_code >= 500:
                    ultimo = BackendErro(f"HTTP_{resp.status_code}", "erro do servidor", tentativa)
                elif resp.status_code >= 400:
                    # erro de negócio/contrato: não retenta
                    raise BackendErro(f"HTTP_{resp.status_code}", resp.text[:200], tentativa)
                else:
                    try:
                        corpo = resp.json()
                    except ValueError as exc:
                        raise BackendErro("RESPOSTA_INVALIDA", "JSON inválido", tentativa) from exc
                    if not isinstance(corpo, dict):
                        raise BackendErro("RESPOSTA_INVALIDA", "esperado objeto JSON", tentativa)
                    return corpo
            if tentativa == 1:
                time.sleep(self.RETRY_BACKOFF_SECONDS)
        assert ultimo is not None
        raise ultimo


def _limpar(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None and v != ""}
