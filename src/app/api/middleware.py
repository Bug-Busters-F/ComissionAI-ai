"""
Proteção e rastreabilidade das chamadas internas (IA-10 / BUG-123).

- `X-Correlation-Id`: recebido do backend (ou gerado), devolvido na resposta e incluído em todos os logs
  da requisição, para cruzar logs Spring × Python.
- `X-Internal-Api-Key` (nome configurável): a MESMA chave que o backend já envia e que a IA usa para
  consultar o backend (`AI_SERVICE_API_KEY`). Comparação em tempo constante; o valor nunca é logado.
  Não é autenticação de usuário: a IA não tem usuários próprios, só confia no backend.

Chave não configurada: em desenvolvimento as rotas ficam abertas (com aviso no log); com
`AI_INBOUND_AUTH_OBRIGATORIA=true` (produção), as rotas protegidas respondem 503 até a chave existir.
"""

from __future__ import annotations

import hmac
import logging
import re
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.erros import corpo_erro

logger = logging.getLogger("app.acesso")

HEADER_CORRELACAO = "X-Correlation-Id"
ROTAS_LIVRES = frozenset({"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
_ID_VALIDO = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

correlacao_atual: ContextVar[str] = ContextVar("correlacao_atual", default="-")


class FiltroCorrelacao(logging.Filter):
    """Injeta `correlation_id` em todo registro de log (formato do basicConfig em main.py)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlacao_atual.get()
        return True


def _correlacao(request: Request) -> str:
    recebido = request.headers.get(HEADER_CORRELACAO, "")
    return recebido if _ID_VALIDO.match(recebido) else uuid.uuid4().hex


def _chave_valida(request: Request) -> JSONResponse | None:
    """None = pode seguir; senão, a resposta de erro."""
    if request.method == "OPTIONS" or request.url.path in ROTAS_LIVRES:
        return None
    esperada = settings.ai_service_api_key
    if not esperada:
        if settings.ai_inbound_auth_obrigatoria:
            return JSONResponse(status_code=503, content=corpo_erro("AUTH_NAO_CONFIGURADA"))
        return None
    recebida = request.headers.get(settings.ai_service_auth_header, "")
    if not recebida or not hmac.compare_digest(recebida.encode("utf-8"), esperada.encode("utf-8")):
        return JSONResponse(status_code=401, content=corpo_erro("CHAVE_INTERNA_INVALIDA"))
    return None


async def rastrear_e_autenticar(request: Request, call_next):
    correlacao = _correlacao(request)
    token = correlacao_atual.set(correlacao)
    inicio = time.perf_counter()
    try:
        negado = _chave_valida(request)
        resposta = negado if negado is not None else await call_next(request)
        resposta.headers[HEADER_CORRELACAO] = correlacao
        logger.info("%s %s -> %s em %.0f ms", request.method, request.url.path, resposta.status_code,
                    (time.perf_counter() - inicio) * 1000)
        return resposta
    finally:
        correlacao_atual.reset(token)


def avisar_configuracao() -> None:
    if not settings.ai_service_api_key:
        if settings.ai_inbound_auth_obrigatoria:
            logger.error("AI_SERVICE_API_KEY ausente e AI_INBOUND_AUTH_OBRIGATORIA=true: rotas protegidas "
                         "responderão 503.")
        else:
            logger.warning("AI_SERVICE_API_KEY ausente: rotas do serviço de IA SEM proteção (apenas desenvolvimento).")
