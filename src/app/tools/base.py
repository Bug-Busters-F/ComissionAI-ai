"""
Base das ferramentas do agente (IA-3, BUG-54).

Resultado padronizado: `SEM_DADOS` (o backend respondeu "não existe") nunca se
confunde com `FALHA` (timeout, indisponibilidade, resposta inválida). Nenhum valor
é preenchido quando o status não é OK/AMBIGUO.
"""

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.proposta import ReferenciaBase

StatusTool = Literal["OK", "SEM_DADOS", "AMBIGUO", "FALHA"]


class ErroTool(BaseModel):
    tipo: str  # TIMEOUT | INDISPONIVEL | RESPOSTA_INVALIDA | HTTP_xxx
    detalhe: str = ""


class ToolResult(BaseModel):
    status: StatusTool
    dados: dict[str, Any] | None = None
    referencias: list[ReferenciaBase] = Field(default_factory=list)
    erro: ErroTool | None = None
    tentativas: int = 1

    @classmethod
    def sem_dados(cls, **kw: Any) -> "ToolResult":
        return cls(status="SEM_DADOS", **kw)

    @classmethod
    def falha(cls, tipo: str, detalhe: str = "", tentativas: int = 1) -> "ToolResult":
        return cls(status="FALHA", erro=ErroTool(tipo=tipo, detalhe=detalhe), tentativas=tentativas)


class Tool(ABC):
    """Contrato de uma ferramenta: nome, descrição para o LLM, schema de entrada e execução."""

    nome: str
    descricao: str
    schema_entrada: type[BaseModel]

    @abstractmethod
    def executar(self, args: BaseModel) -> ToolResult: ...

    def executar_dict(self, argumentos: dict[str, Any]) -> ToolResult:
        """Valida os argumentos (vindos do LLM) antes de executar."""
        try:
            args = self.schema_entrada.model_validate(argumentos)
        except Exception as exc:  # ValidationError
            return ToolResult.falha("ARGUMENTOS_INVALIDOS", str(exc)[:300])
        return self.executar(args)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def registrar(self, tool: Tool) -> None:
        self._tools[tool.nome] = tool

    def obter(self, nome: str) -> Tool | None:
        return self._tools.get(nome)

    def nomes(self) -> list[str]:
        return sorted(self._tools)

    def descricoes(self) -> list[dict[str, Any]]:
        return [
            {"nome": t.nome, "descricao": t.descricao, "argumentos": t.schema_entrada.model_json_schema()}
            for t in self._tools.values()
        ]
