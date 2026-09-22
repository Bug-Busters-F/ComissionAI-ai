"""
Factory de provedores de LLM (Strategy Pattern).

Lê LLM_PROVIDER e retorna a implementação concreta correta.
Imports são lazy para não carregar SDKs não instalados.
"""

from app.core.config import settings
from app.providers.base import LLMProvider


def get_provider() -> LLMProvider:
    """Retorna a instância do provedor configurado em LLM_PROVIDER."""
    name = settings.llm_provider.lower()

    match name:
        case "gemini":
            from app.providers.gemini import GeminiProvider
            return GeminiProvider()
        case "openai":
            from app.providers.openai import OpenAIProvider
            return OpenAIProvider()
        case "anthropic":
            from app.providers.anthropic import AnthropicProvider
            return AnthropicProvider()
        case "groq":
            from app.providers.groq import GroqProvider
            return GroqProvider()
        case _:
            raise ValueError(
                f"Provedor de LLM desconhecido: '{name}'. "
                "Valores aceitos: gemini, openai, anthropic, groq."
            )


__all__ = ["get_provider", "LLMProvider"]
