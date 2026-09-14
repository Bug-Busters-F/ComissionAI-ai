"""
Contrato base para todos os provedores de LLM (Strategy Pattern).

Todo provedor concreto deve herdar de LLMProvider e implementar
o método `complete`. O restante do sistema depende apenas desta
interface — nunca de uma implementação específica.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Interface que todos os provedores de LLM devem implementar."""

    @abstractmethod
    def complete(self, prompt: str, response_schema: dict) -> dict:
        """
        Envia o prompt ao LLM e retorna a resposta como dicionário.

        Args:
            prompt:          Texto completo montado pela camada core.
            response_schema: JSON Schema (gerado pelo Pydantic) que o
                             provedor usa para forçar saída estruturada.

        Returns:
            Dicionário com os campos definidos pelo response_schema.

        Raises:
            LLMAuthenticationError: Se a chave de API for inválida ou não autorizada.
            LLMRateLimitError: Se a cota ou limite de requisições do provedor for excedido.
            LLMTimeoutError: Se o provedor demorar mais que o tempo limite configurado.
            LLMProviderError: Em falhas internas, de conexão ou indisponibilidade do serviço.
            LLMResponseParsingError: Se a resposta retornada não puder ser convertida em JSON.
        """
        ...
