"""
Exceções de domínio para a camada de LLM e provedores (Task S1-A03).

Estas exceções encapsulam falhas de SDKs específicos (Gemini, OpenAI, Anthropic)
em tipos padronizados, garantindo que credenciais e segredos não sejam expostos.
"""


class LLMBaseException(Exception):
    """Exceção base para todas as falhas de comunicação ou processamento de LLM."""

    def __init__(self, message: str, status_code: int = 502, error_code: str = "LLM_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class LLMAuthenticationError(LLMBaseException):
    """Falha de autenticação ou chave de API inválida/ausente."""

    def __init__(self, message: str = "Falha de autenticação com o provedor de LLM. Verifique as credenciais configuradas.") -> None:
        super().__init__(message=message, status_code=401, error_code="LLM_AUTH_ERROR")


class LLMRateLimitError(LLMBaseException):
    """Limite de requisições ou cota do provedor de LLM excedida."""

    def __init__(self, message: str = "Limite de cota ou taxa de requisições excedido junto ao provedor de LLM.") -> None:
        super().__init__(message=message, status_code=429, error_code="LLM_RATE_LIMIT_ERROR")


class LLMTimeoutError(LLMBaseException):
    """Tempo limite de resposta do provedor de LLM excedido."""

    def __init__(self, message: str = "Tempo limite excedido ao aguardar resposta do provedor de LLM.") -> None:
        super().__init__(message=message, status_code=504, error_code="LLM_TIMEOUT_ERROR")


class LLMProviderError(LLMBaseException):
    """Erro interno ou indisponibilidade no serviço do provedor de LLM."""

    def __init__(self, message: str = "Erro interno no serviço do provedor de LLM.") -> None:
        super().__init__(message=message, status_code=502, error_code="LLM_PROVIDER_ERROR")


class LLMResponseParsingError(LLMBaseException):
    """Falha ao decodificar a resposta estruturada retornada pelo LLM."""

    def __init__(self, message: str = "Não foi possível interpretar a resposta estruturada retornada pelo modelo.") -> None:
        super().__init__(message=message, status_code=502, error_code="LLM_PARSING_ERROR")
