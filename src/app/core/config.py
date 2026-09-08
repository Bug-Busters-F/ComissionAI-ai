from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configurações centrais do serviço.
    Lidas automaticamente das variáveis de ambiente ou do arquivo .env.
    """

    # --- LLM ---
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = ""

    # --- API ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
