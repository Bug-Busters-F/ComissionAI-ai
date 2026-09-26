from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações centrais do serviço.
    Lidas automaticamente das variáveis de ambiente ou do arquivo .env.
    """

    # --- LLM ---
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_sdk: str = ""  # usado apenas para build Docker (ex: google-genai, openai)
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 30
    llm_max_output_tokens: int = 1024

    # --- API ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
