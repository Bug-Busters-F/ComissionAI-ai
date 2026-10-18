"""Decisão do agente (saída estruturada do LLM) e sua validação."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class DecisaoAgente(BaseModel):
    """O LLM só PEDE; quem valida e executa é o Python."""

    acao: Literal["CONSULTAR", "FINALIZAR"]
    lacunaId: str | None = Field(
        default=None, description="Id da lacuna que a consulta resolve (um dos ids listados)."
    )
    ferramenta: str | None = Field(default=None, description="Nome da ferramenta a chamar.")
    argumentos: dict[str, Any] | None = Field(default=None, description="Argumentos da ferramenta.")
    justificativa: str = Field(default="", description="Motivo curto da decisão (vai para a trilha).")
