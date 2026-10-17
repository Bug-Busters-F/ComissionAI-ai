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

    # --- Backend (Spring) consultado pelas tools do agente ---
    backend_base_url: str = "http://localhost:8080"
    tool_timeout_seconds: float = 5.0

    # --- Agente ---
    agent_max_steps: int = 6
    agent_max_tool_calls: int = 8
    agent_max_duration_seconds: float = 45.0
    agent_max_code_executions: int = 5

    # --- Simulação / sandbox ---
    sim_max_seconds: float = 10.0
    sim_max_memory_mb: int = 256
    sim_max_output_kb: int = 512
    sim_max_registros: int = 50000
    sim_max_cenarios: int = 5
    sim_max_code_lines: int = 150
    sim_max_code_bytes: int = 8192

    # --- API ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
