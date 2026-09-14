"""
Módulo de Schemas Pydantic da aplicação.
"""

from app.schemas.raw import InterpretacaoRegraRawLLM
from app.schemas.regra import (
    InterpretacaoRegraRequest,
    InterpretacaoRegraResponse,
)

__all__ = [
    "InterpretacaoRegraRequest",
    "InterpretacaoRegraResponse",
    "InterpretacaoRegraRawLLM",
]
