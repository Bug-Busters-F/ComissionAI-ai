"""Ferramentas de consulta ao backend usadas pelo agente."""

from app.tools.bases import ConsultarBaseComissao
from app.tools.base import ToolRegistry
from app.tools.cadastros import ResolverPublico, ValidarMatricula
from app.tools.client import BackendClient
from app.tools.concorrencia import ConsultarRegrasConcorrentes
from app.tools.simulacao import ObterDadosSimulacao


def criar_registry(client: BackendClient | None = None, incluir_simulacao: bool = False) -> ToolRegistry:
    client = client or BackendClient()
    registry = ToolRegistry()
    for tool in (
        ResolverPublico(client),
        ValidarMatricula(client),
        ConsultarBaseComissao(client),
        ConsultarRegrasConcorrentes(client),
    ):
        registry.registrar(tool)
    if incluir_simulacao:
        registry.registrar(ObterDadosSimulacao(client))
    return registry


__all__ = ["criar_registry", "BackendClient"]
