"""
Provedor OpenAI.

SDK: openai
Variáveis de ambiente:
    LLM_PROVIDER=openai
    LLM_API_KEY=<sua-chave-openai>
    LLM_MODEL=gpt-4o-mini   (default)
"""

from app.core.config import settings
from app.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "SDK da OpenAI não instalado. Execute: pip install openai"
            ) from e

        self._client = OpenAI(api_key=settings.llm_api_key)
        self._model = settings.llm_model or "gpt-4o-mini"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama a OpenAI com saída estruturada via JSON Schema."""
        import json

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "resposta",
                    "schema": response_schema,
                    "strict": True,
                },
            },
        )
        return json.loads(response.choices[0].message.content)
