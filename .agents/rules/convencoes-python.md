# Convenções Python — Serviço de IA

## Estrutura de Pastas

```
src/app/
├── main.py                  ← ponto de entrada FastAPI; só registra routers
├── api/
│   └── routes/              ← uma rota por arquivo; apenas entrada/saída HTTP
├── core/                    ← montagem de prompt e orquestração do fluxo
├── schemas/                 ← modelos Pydantic compartilhados com o Spring
└── providers/               ← integração com LLM (Strategy Pattern)
    ├── __init__.py          ← factory get_provider()
    ├── base.py              ← ABC LLMProvider
    ├── gemini.py
    ├── openai.py
    └── anthropic.py
```

## Separação de Camadas — Regra Fundamental

As três camadas abaixo DEVEM permanecer separadas:

1. **`api/routes/`** — recebe request HTTP, chama `core/`, devolve response. Sem lógica de negócio.
2. **`core/`** — monta prompt, orquestra chamada ao provedor, aplica normalização e validação.
3. **`providers/`** — única camada que conhece o SDK do LLM. Recebe prompt + schema, devolve dict.

Se essas camadas forem coladas num arquivo só, adicionar o laço de tools na Sprint 2 vira reescrita.
Separadas, vira acréscimo.

## Design Pattern — Strategy (Providers)

- `LLMProvider` (em `providers/base.py`) é a interface (ABC).
- Cada provedor concreto (`GeminiProvider`, `OpenAIProvider`, `AnthropicProvider`) implementa `complete(prompt, response_schema) -> dict`.
- A factory `get_provider()` (em `providers/__init__.py`) lê `LLM_PROVIDER` do ambiente e retorna a instância correta.
- O `core/` depende apenas de `LLMProvider` — nunca de uma implementação específica.
- Imports dos SDKs são lazy (dentro do `__init__`) para não carregar SDKs não instalados.

## Configuração

- Todas as configurações ficam em `core/config.py` via `pydantic-settings`.
- Variáveis de ambiente são lidas do `.env` (nunca versionado) ou do ambiente do container.
- O `.env.example` (versionado) serve de referência para novos membros.

## Variáveis de Ambiente

| Variável       | Descrição                              | Default          |
|----------------|----------------------------------------|------------------|
| `LLM_PROVIDER` | Provedor ativo: gemini, openai, anthropic | `gemini`      |
| `LLM_API_KEY`  | Chave de API do provedor               | (obrigatório)    |
| `LLM_MODEL`    | Modelo específico (vazio = default)    | `""`             |
| `APP_PORT`     | Porta do servidor                      | `8000`           |
| `APP_RELOAD`   | Hot reload (desenvolvimento)           | `false`          |

## Convenções de Código

- Linguagem: **português** para docstrings, comentários e mensagens de erro voltadas ao time.
- Type hints em todos os métodos públicos.
- Docstrings em todas as classes e métodos públicos.
- Nunca suprimir ou remover docstrings e comentários existentes ao editar um arquivo.
- `ValidationError` do Pydantic deve ser capturado e convertido em resposta HTTP estruturada — nunca vazar stack trace ao Spring.

## Execução Local

```bash
# Com venv ativo:
python -m uvicorn app.main:app --reload --app-dir src

# Via Docker:
docker compose up --build
```

Health check: `GET /health` → `{"status": "ok"}`
Swagger: `http://localhost:8000/docs`
