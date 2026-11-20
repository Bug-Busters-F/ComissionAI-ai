"""
Catálogo de `error_code` do serviço de IA (IA-10). Todo erro HTTP sai como
`{"detail": "<mensagem>", "error_code": "<código>"}` (+ `erros` na validação) e com `X-Correlation-Id`.

Falhas de domínio que NÃO são erro HTTP (a resposta é 200 e explica o que faltou):
`pendencias[]` (ex.: SIMULACAO_NAO_VALIDADA, CAMPO_AUSENTE), `statusSugestoes = FALHA`,
`calibracoes[].status = FALHA | SEM_SOLUCAO_VIAVEL` e grupos `AMOSTRA_INSUFICIENTE` nas anomalias.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErroCatalogado:
    status: int
    mensagem: str
    acao_backend: str


CATALOGO: dict[str, ErroCatalogado] = {
    "CHAVE_INTERNA_INVALIDA": ErroCatalogado(
        401, "Chave interna ausente ou inválida.",
        "Conferir AI_SERVICE_API_KEY/AI_SERVICE_AUTH_HEADER iguais no backend e na IA. Não repetir."),
    "AUTH_NAO_CONFIGURADA": ErroCatalogado(
        503, "Serviço de IA sem chave interna configurada.",
        "Configurar AI_SERVICE_API_KEY no serviço de IA."),
    "VALIDACAO_ENTRADA": ErroCatalogado(
        422, "Requisição inválida.", "Corrigir o payload conforme `erros[]`. Não repetir igual."),
    "NAO_ENCONTRADO": ErroCatalogado(404, "Recurso não encontrado.", "Conferir a rota ou a assinatura."),
    "VOLUME_EXCEDIDO": ErroCatalogado(
        413, "Volume acima do limite configurado.", "Reduzir o recorte ou ajustar o limite (ANOMALIA_MAX_VENDAS, EXEC_MAX_ITENS)."),
    "PROGRAMA_REJEITADO": ErroCatalogado(
        422, "Programa Python rejeitado pela análise estática.",
        "Corrigir o programa (ver `violacoes`) e reaprovar. Não repetir igual."),
    "PROGRAMA_FALHOU": ErroCatalogado(
        422, "O programa Python falhou durante a execução no sandbox.",
        "Ver `erro`/`detalhe` (item, exceção, limite de tempo ou memória). Nenhum resultado parcial é devolvido."),
    "METODO_NAO_PERMITIDO": ErroCatalogado(405, "Método HTTP não permitido.", "Conferir o método da rota."),
    "LLM_AUTH_ERROR": ErroCatalogado(401, "Falha de autenticação no provedor de LLM.", "Conferir LLM_API_KEY."),
    "LLM_RATE_LIMIT_ERROR": ErroCatalogado(
        429, "Cota do provedor de LLM esgotada.", "Respeitar Retry-After antes de tentar de novo."),
    "LLM_TIMEOUT_ERROR": ErroCatalogado(504, "Tempo limite do LLM excedido.", "Tentar novamente mais tarde."),
    "LLM_PROVIDER_ERROR": ErroCatalogado(502, "Falha no provedor de LLM.", "Tentar novamente mais tarde."),
    "LLM_PARSING_ERROR": ErroCatalogado(502, "Resposta do LLM em formato inválido.", "Tentar novamente."),
    "HTTP_ERROR": ErroCatalogado(400, "Erro na requisição.", "Ver `detail`."),
    "INTERNAL_ERROR": ErroCatalogado(500, "Erro interno inesperado no serviço de IA.", "Registrar o X-Correlation-Id."),
}

_POR_STATUS = {401: "CHAVE_INTERNA_INVALIDA", 404: "NAO_ENCONTRADO", 405: "METODO_NAO_PERMITIDO",
               413: "VOLUME_EXCEDIDO", 422: "VALIDACAO_ENTRADA", 500: "INTERNAL_ERROR"}


def codigo_por_status(status: int) -> str:
    return _POR_STATUS.get(status, "HTTP_ERROR")


def corpo_erro(codigo: str, detalhe: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"detail": detalhe or CATALOGO[codigo].mensagem, "error_code": codigo, **extra}
