from pydantic import Field
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
    # Groq: retentativa somente com Retry-After válido, dentro do timeout da chamada.
    llm_rate_limit_max_retries: int = Field(default=1, ge=0, le=2)
    llm_rate_limit_max_wait_seconds: float = Field(default=5.0, ge=0, le=30)

    # --- Backend (Spring) consultado pelas tools do agente ---
    backend_base_url: str = "http://localhost:8080"
    tool_timeout_seconds: float = 5.0
    # Mesma chave usada pelo backend; nunca recebida do navegador.
    ai_service_api_key: str = ""
    ai_service_auth_header: str = "X-Internal-Api-Key"
    # IA-10: a mesma chave protege as rotas de ENTRADA. true = sem chave configurada, responde 503 (produção).
    ai_inbound_auth_obrigatoria: bool = False

    # --- Agente ---
    # Por padrão, só a extração usa o modelo; as consultas têm argumentos conhecidos.
    agent_use_llm_decisions: bool = False
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
    sim_dir_programas: str = "data/programas_gerados"

    # --- Execução do programa aprovado no backend (/api/v2/executar-programa, IA-10 / BACK-9) ---
    # Itens = vendas × cenários (simulação manda 4 por venda). O tempo precisa caber no AI_READ_TIMEOUT (60 s).
    # O programa vem do backend com regras embutidas no código, por isso o limite de tamanho é maior que o do
    # código gerado pelo LLM; a análise estática por lista de permissão é a mesma.
    exec_max_itens: int = Field(default=200000, ge=1)
    exec_max_seconds: float = Field(default=30.0, gt=0, le=120)
    exec_max_output_kb: int = Field(default=16384, ge=64)
    exec_max_code_lines: int = Field(default=1000, ge=10)
    exec_max_code_bytes: int = Field(default=131072, ge=1024)

    # --- Calibração (IA-6): reexecuções por cenário e tempo total da requisição ---
    # O tempo total precisa caber no read-timeout do backend (AI_READ_TIMEOUT, 60 s) junto com a simulação.
    calib_max_tentativas: int = Field(default=12, ge=2, le=30)
    calib_max_segundos: float = Field(default=20.0, gt=0, le=120)

    # --- Anomalias (IA-8): IQR de Tukey por grupo marca + cargo ---
    anomalia_k: float = Field(default=1.5, gt=0, le=10)
    anomalia_amostra_minima: int = Field(default=8, ge=4, le=1000)
    anomalia_max_vendas: int = Field(default=200000, ge=1)

    # --- API ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
