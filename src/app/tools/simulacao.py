"""Ferramenta de dados para simulação: vendas da competência, paginadas e limitadas."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.tools.base import Tool, ToolResult
from app.tools.client import BackendClient, BackendErro

TAMANHO_PAGINA = 1000


class DadosSimulacaoArgs(BaseModel):
    competencia: str = Field(pattern=r"^\d{4}-\d{2}$")
    marca: int | None = None
    loja: int | None = None
    cargo: int | None = None
    matricula: str | None = None


class ObterDadosSimulacao(Tool):
    nome = "obter_dados_simulacao"
    descricao = (
        "Obtém as vendas da competência (com filtros opcionais) para simulação. "
        "Limitado por SIM_MAX_REGISTROS; acima disso devolve FALHA, nunca dados parciais."
    )
    schema_entrada = DadosSimulacaoArgs

    def __init__(self, client: BackendClient) -> None:
        self._client = client

    def executar(self, args: DadosSimulacaoArgs) -> ToolResult:  # type: ignore[override]
        vendas: list[dict[str, Any]] = []
        pagina = 0
        while True:
            try:
                corpo = self._client.get(
                    "/dados-simulacao",
                    {
                        "competencia": args.competencia,
                        "marca": args.marca,
                        "loja": args.loja,
                        "cargo": args.cargo,
                        "matricula": args.matricula,
                        "page": pagina,
                        "size": TAMANHO_PAGINA,
                    },
                )
            except BackendErro as exc:
                return ToolResult.falha(exc.tipo, exc.detalhe, exc.tentativas)
            conteudo = corpo.get("content")
            if not isinstance(conteudo, list):
                return ToolResult.falha("RESPOSTA_INVALIDA", "campo 'content' ausente")
            vendas += conteudo
            if len(vendas) > settings.sim_max_registros:
                return ToolResult.falha(
                    "LIMITE_REGISTROS",
                    f"mais de {settings.sim_max_registros} registros; restrinja o filtro",
                )
            if corpo.get("last", True) or not conteudo:
                break
            pagina += 1
        if not vendas:
            return ToolResult.sem_dados()
        return ToolResult(status="OK", dados={"vendas": vendas, "total": len(vendas)})
