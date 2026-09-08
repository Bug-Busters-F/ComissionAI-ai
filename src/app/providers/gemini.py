"""
Provedor Google Gemini.

SDK: google-generativeai
Variáveis de ambiente:
    LLM_PROVIDER=gemini
    LLM_API_KEY=<sua-chave-gemini>
    LLM_MODEL=gemini-1.5-flash   (default)
"""

from app.core.config import settings
from app.providers.base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "SDK do Gemini não instalado. Execute: pip install google-generativeai"
            ) from e

        genai.configure(api_key=settings.llm_api_key)
        model_name = settings.llm_model or "gemini-1.5-flash"
        self._model = genai.GenerativeModel(model_name)

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama o Gemini com saída estruturada via response_schema."""
        import google.generativeai as genai

        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        response = self._model.generate_content(
            prompt,
            generation_config=generation_config,
        )
        import json
        return json.loads(response.text)
