"""
Módulo de Schemas Pydantic da aplicação.
"""

from src.app.schemas.regra import (
    InterpretacaoRegraRequest,
    InterpretacaoRegraResponse,
)

__all__ = [
    "InterpretacaoRegraRequest",
    "InterpretacaoRegraResponse",
]
