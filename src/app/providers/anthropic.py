"""
Provedor Anthropic Claude.

SDK: anthropic
Variáveis de ambiente:
    LLM_PROVIDER=anthropic
    LLM_API_KEY=<sua-chave-anthropic>
    LLM_MODEL=claude-3-5-haiku-20241022   (default)
"""

from app.core.config import settings
from app.core.exceptions import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseParsingError,
    LLMTimeoutError,
)
from app.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "SDK da Anthropic não instalado. Execute: pip install anthropic"
            ) from e

        if not settings.llm_api_key:
            raise LLMAuthenticationError(
                "Chave de API da Anthropic (LLM_API_KEY) não configurada no ambiente."
            )

        self._client = anthropic.Anthropic(
            api_key=settings.llm_api_key,
            timeout=float(settings.llm_timeout_seconds),
        )
        self._model = settings.llm_model or "claude-3-5-haiku-20241022"

    def complete(self, prompt: str, response_schema: dict) -> dict:
        """Chama o Claude com saída estruturada via tool use."""
        import anthropic

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=settings.llm_max_output_tokens,
                temperature=settings.llm_temperature,
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
        except anthropic.AuthenticationError:
            raise LLMAuthenticationError(
                "Credenciais inválidas ou não autorizadas para a Anthropic."
            ) from None
        except (anthropic.RateLimitError, anthropic.PermissionDeniedError):
            raise LLMRateLimitError(
                "Limite de requisições ou cota excedida na API da Anthropic."
            ) from None
        except (anthropic.APITimeoutError, TimeoutError):
            raise LLMTimeoutError(
                f"Tempo limite ({settings.llm_timeout_seconds}s) excedido ao comunicar com a Anthropic."
            ) from None
        except (anthropic.APIConnectionError, anthropic.InternalServerError, anthropic.APIStatusError):
            raise LLMProviderError(
                "Erro de comunicação ou indisponibilidade no serviço Anthropic."
            ) from None
        except Exception as e:
            if isinstance(e, (LLMAuthenticationError, LLMRateLimitError, LLMTimeoutError, LLMProviderError)):
                raise e
            raise LLMProviderError(
                "Falha inesperada ao executar chamada à Anthropic."
            ) from None

        tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if not tool_blocks:
            raise LLMResponseParsingError(
                "O modelo Anthropic não retornou o bloco estruturado de tool use esperado."
            )

        tool_input = tool_blocks[0].input
        if not isinstance(tool_input, dict):
            raise LLMResponseParsingError("A saída do tool use da Anthropic não é um dicionário válido.")

        return tool_input
