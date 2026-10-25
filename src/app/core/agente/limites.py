"""Orçamento de execução do agente: passos, chamadas de ferramenta e tempo."""

import time
from dataclasses import dataclass, field
from typing import Callable

from app.core.config import settings


@dataclass
class Limites:
    max_steps: int = field(default_factory=lambda: settings.agent_max_steps)
    max_tool_calls: int = field(default_factory=lambda: settings.agent_max_tool_calls)
    max_duration_seconds: float = field(default_factory=lambda: settings.agent_max_duration_seconds)
    max_code_executions: int = field(default_factory=lambda: settings.agent_max_code_executions)


class Orcamento:
    """Controla o consumo dos limites; `relogio` é injetável para teste."""

    def __init__(self, limites: Limites | None = None, relogio: Callable[[], float] = time.monotonic) -> None:
        self.limites = limites or Limites()
        self._relogio = relogio
        self._inicio = relogio()
        self.passos = 0
        self.chamadas = 0
        self.execucoes_codigo = 0

    @property
    def decorrido(self) -> float:
        return self._relogio() - self._inicio

    @property
    def restante(self) -> float:
        return max(0.0, self.limites.max_duration_seconds - self.decorrido)

    def motivo_parada(self) -> str | None:
        """Retorna o motivo se algum limite foi atingido; None se ainda há orçamento."""
        if self.passos >= self.limites.max_steps:
            return f"limite de {self.limites.max_steps} etapas"
        if self.chamadas >= self.limites.max_tool_calls:
            return f"limite de {self.limites.max_tool_calls} chamadas de ferramenta"
        if self.decorrido >= self.limites.max_duration_seconds:
            return f"limite de {self.limites.max_duration_seconds:g}s de duração"
        return None
