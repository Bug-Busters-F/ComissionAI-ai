"""
Provedor Anthropic Claude.

SDK: anthropic
Variáveis de ambiente:
    LLM_PROVIDER=anthropic
    LLM_API_KEY=<sua-chave-anthropic>
    LLM_MODEL=claude-3-5-haiku-20241022   (default)
"""

from app.core.config import settings
from app.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "SDK da Anthropic não instalado. Execute: pip install anthropic"
            ) from e

        self._client = anthropic.Anthropic(api_key=settings.llm_api_key)
        self._model = settings.llm_model or "claude-3-5-haiku-20241022"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama o Claude com saída estruturada via tool use."""
        import json

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            tools=[
                {
                    "name": "resposta_estruturada",
                    "description": "Retorna a resposta no formato estruturado exigido.",
                    "input_schema": response_schema,
                }
            ],
            tool_choice={"type": "tool", "name": "resposta_estruturada"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_block = next(
            b for b in response.content if b.type == "tool_use"
        )
        return tool_block.input
