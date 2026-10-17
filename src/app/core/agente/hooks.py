"""
Pontos de extensão do agente. Por padrão são identidade (no-op).

O Humberto (IA-5, IA-7, IA-9) pluga a lógica de ajustes sobre a base, explicação/código
e validações finais SEM alterar o laço. Mudou a assinatura => avisar no PR.
"""

from typing import Any, Protocol

from app.core.services.campanha import BlocoInterno
from app.schemas.proposta import BlocoProposta
from app.tools.base import ToolResult


class Hooks(Protocol):
    def pos_extracao(self, blocos: list[BlocoInterno], ctx: dict[str, Any]) -> list[BlocoInterno]: ...

    def pos_consulta(self, bloco: BlocoInterno, ferramenta: str, resultado: ToolResult) -> BlocoInterno: ...

    def antes_de_fechar(self, blocos: list[BlocoProposta], ctx: dict[str, Any]) -> list[BlocoProposta]: ...


class HooksPadrao:
    """No-op: devolve exatamente o que recebeu."""

    def pos_extracao(self, blocos: list[BlocoInterno], ctx: dict[str, Any]) -> list[BlocoInterno]:
        return blocos

    def pos_consulta(self, bloco: BlocoInterno, ferramenta: str, resultado: ToolResult) -> BlocoInterno:
        return bloco

    def antes_de_fechar(self, blocos: list[BlocoProposta], ctx: dict[str, Any]) -> list[BlocoProposta]:
        return blocos
