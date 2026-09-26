# Guia de Execução, Empacotamento e Integração do Serviço de IA

Este documento reúne todas as orientações necessárias para **empacotar**, **configurar**, **executar**, **integrar** e **diagnosticar** o microsserviço de Inteligência Artificial da equipe Bug Busters no contexto do **Sprint 1** (Tarefas **S1-A10**, integração com ambiente integrado **S1-B13** e composição do manual **S1-B14**).

---

## 1. Visão Geral e Arquitetura

O serviço de IA é uma API REST desenvolvida em **Python 3.12** com **FastAPI** e **Pydantic V2**. Sua responsabilidade no MVP (Sprint 1) é atuar como motor de interpretação de regras de negócio em linguagem natural digitadas pelos gestores, convertendo-as em estruturas de comissionamento normalizadas.

### Princípios da Arquitetura
1. **Stateless e sem banco de negócio:** O serviço não se conecta ao banco de dados relacional. Toda informação de contexto necessária (dicionários de marcas, cargos e canais) é injetada pelo backend Spring na requisição.
2. **Isolamento de acesso:** O front-end (Vue.js) **nunca** se comunica diretamente com o serviço de IA. O front se comunica com o Spring Boot, que enriquece a chamada e aciona o serviço de IA.
3. **LLM não é a fonte da verdade:** O modelo de linguagem extrai as intenções e entidades do texto; a validação, normalização de tipos, cálculo de confiança e regras determinísticas são executadas pelo código Python e validadas pelo Spring.

---

## 2. Empacotamento e Inicialização

O serviço está totalmente empacotado para execução em containers Docker ou execução local direta em ambiente de desenvolvimento.

### 2.1 Execução via Docker Compose (Recomendado para S1-B13)

Ideal para o ambiente integrado unificado da equipe.

#### Pré-requisitos
- [Docker](https://docs.docker.com/get-docker/) instalado e em execução (Engine >= 24.0)
- [Docker Compose](https://docs.docker.com/compose/) (v2 integrado ao Docker CLI)

#### Passo a passo
1. Copie o arquivo de exemplo de ambiente e preencha suas variáveis:
   ```bash
   cp .env.example .env
   ```
2. Defina pelo menos sua chave de API (`LLM_API_KEY`) no arquivo `.env`.
3. Construa a imagem e inicie o container:
   ```bash
   # Construir imagem e rodar em segundo plano
   docker compose up --build -d
   ```
4. Verifique se o container está ativo e saudável:
   ```bash
   docker compose ps
   docker compose logs -f ai
   ```
5. Teste o endpoint de saúde:
   ```bash
   curl http://localhost:8000/health
   # Retorno esperado: {"status": "ok"}
   ```

#### Parar o serviço
```bash
docker compose down
```

#### Customização do SDK no Build
O `Dockerfile` e o `docker-compose.yml` suportam o argumento de build `LLM_SDK`. Caso deseje construir a imagem com outro provedor (por exemplo, `groq` ou `openai`), basta alterar a variável `LLM_SDK` no `.env` ou executar:
```bash
docker compose build --build-arg LLM_SDK=groq
```

---

### 2.2 Execução Local Direta (Desenvolvimento e Testes)

#### Pré-requisitos
- Python 3.12 ou superior instalado
- Git instalado

#### Passo a passo
1. **Criar e ativar o ambiente virtual (venv):**
   - **Linux / macOS:**
     ```bash
     python -m venv venv
     source venv/bin/activate
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```

2. **Instalar dependências base do projeto:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Instalar o SDK do provedor de LLM escolhido:**
   ```bash
   # Provedor padrão oficial (Gemini):
   pip install google-genai

   # Ou alternativas suportadas:
   pip install groq        # Para Groq
   pip install openai      # Para OpenAI
   pip install anthropic   # Para Anthropic
   ```

4. **Configurar variáveis de ambiente:**
   ```bash
   cp .env.example .env
   # Edite o .env configurando LLM_PROVIDER e LLM_API_KEY
   ```

5. **Iniciar o servidor de desenvolvimento:**
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir src --reload
   ```

---

### 2.3 Endpoints Disponibilizados

| Rota | Método | Descrição |
|---|---|---|
| `/health` | `GET` | Health check básico para monitoramento / readiness probe |
| `/api/v1/interpretar` | `POST` | Rota principal de interpretação de regras em linguagem natural |
| `/docs` | `GET` | Documentação interativa OpenAPI / Swagger UI |
| `/redoc` | `GET` | Documentação técnica ReDoc |

---

## 3. Configurações e Variáveis de Ambiente

O serviço utiliza o `pydantic-settings` para gerenciar parâmetros a partir do arquivo `.env` ou variáveis do sistema operacional.

### Tabela Completa de Parâmetros

| Variável | Tipo | Obrigatório | Padrão | Descrição |
|---|---|---|---|---|
| `LLM_PROVIDER` | string | Sim | `gemini` | Provedor de LLM ativo (`gemini`, `groq`, `openai`, `anthropic`). |
| `LLM_SDK` | string | Não | `google-genai` | SDK a ser instalado durante o build da imagem Docker (`google-genai`, `groq`, `openai`, `anthropic`). |
| `LLM_API_KEY` | string | Sim | *vazio* | Chave de autenticação na API do provedor selecionado. |
| `LLM_MODEL` | string | Não | *padrão do provedor* | Identificador do modelo no provedor (ex: `gemini-3.6-flash`, `llama-3.3-70b-versatile`, `gpt-4o-mini`). |
| `LLM_TEMPERATURE` | float | Não | `0.0` | Temperatura de inferência. Manter em `0.0` para determinismo e fidelidade estrutural. |
| `LLM_TIMEOUT_SECONDS` | int | Não | `30` | Tempo máximo em segundos para resposta do provedor de LLM. |
| `LLM_MAX_OUTPUT_TOKENS`| int | Não | `1024` | Limite de tokens na resposta gerada pelo LLM. |
| `APP_HOST` | string | Não | `0.0.0.0` | IP em que o Uvicorn aceita conexões. |
| `APP_PORT` | int | Não | `8000` | Porta em que o serviço escuta requisições. |
| `APP_RELOAD` | bool | Não | `false` | Habilita hot reload do Uvicorn (usar apenas em desenvolvimento). |

### Diretrizes de Segurança de Segredos
- **Nunca comite chaves de API ou arquivos `.env` no Git.** O repositório já ignora `.env` via `.gitignore` e `.dockerignore`.
- Em pipelines CI/CD ou no ambiente integrado da entrega (S1-B13), a `LLM_API_KEY` deve ser alimentada via secrets do GitHub Actions, variáveis de ambiente do host ou gerenciador de segredos.

---

## 4. Modelo e Provedor Selecionado para o MVP

### 4.1 Provedor Oficial do MVP: Google Gemini (`gemini-3.6-flash`)
- **Motivação:** Suporte nativo robusto a Structured Outputs via JSON Schema (`response_schema`), excelente compreensão semântica do português brasileiro, baixa latência e tier gratuito acessível para desenvolvimento acadêmico.
- **Configuração no `.env`:**
  ```ini
  LLM_PROVIDER=gemini
  LLM_SDK=google-genai
  LLM_API_KEY=AIzaSy...
  LLM_MODEL=gemini-3.6-flash
  ```

### 4.2 Provedores Alternativos Suportados (Strategy Pattern)
O serviço foi desenhado com o padrão **Strategy**, permitindo alternar de provedor a qualquer momento apenas alterando o `.env`:

| Provedor | Modelo Sugerido | Variáveis de Referência |
|---|---|---|
| **Groq** | `llama-3.3-70b-versatile` ou `openai/gpt-oss-20b` | `LLM_PROVIDER=groq`<br>`LLM_SDK=groq` |
| **OpenAI** | `gpt-4o-mini` | `LLM_PROVIDER=openai`<br>`LLM_SDK=openai` |
| **Anthropic** | `claude-3-5-haiku-20241022` | `LLM_PROVIDER=anthropic`<br>`LLM_SDK=anthropic` |

---

## 5. Conectividade com o Backend Spring Boot (S1-B13)

### 5.1 Topologia de Rede no Ambiente Integrado
- **Cenário 1: Tudo em Docker Compose Compartilhado (Rede Docker integrada):**
  - O Spring acessa o serviço pelo hostname do container:
    ```
    http://bugbusters-ai:8000
    # ou http://ai:8000 (dependendo do service name no compose unificado)
    ```
- **Cenário 2: Spring rodando localmente (host) e IA no Docker ou venv:**
  - O Spring acessa via:
    ```
    http://localhost:8000
    ```

### 5.2 Configuração Sugerida no `application.yml` do Spring Boot
```yaml
ai:
  service:
    base-url: ${AI_SERVICE_URL:http://localhost:8000}
    connect-timeout-ms: 5000
    # A IA tem timeout de 30s + retry. O Spring deve esperar pelo menos 35s:
    read-timeout-ms: 35000
```

### 5.3 Liveness / Readiness Check pelo Spring
Antes de enviar solicitações ou na inicialização da aplicação, o Spring pode verificar o estado do serviço através de:
- **`GET /health`**
- Resposta `200 OK`: `{"status": "ok"}`

### 5.4 Mapeamento de Status Codes e Erros para o Spring

Todas as respostas de erro da IA seguem o formato padronizado:
```json
{
  "detail": "Mensagem detalhada e legível",
  "error_code": "LLM_XXX_ERROR"
}
```

| HTTP Status | `error_code` | Causa | Conduta Recomendada no Spring Boot |
|---|---|---|---|
| **`401`** | `LLM_AUTH_ERROR` | `LLM_API_KEY` ausente ou inválida no serviço de IA. | **Falha de infraestrutura.** Alertar time de sustentação/DevOps. Não reportar como erro do usuário final. |
| **`429`** | `LLM_RATE_LIMIT_ERROR` | Cota ou limite de requisições por minuto do provedor excedido. | Repassar mensagem amigável ao usuário ("Muitas requisições simultâneas. Tente novamente em instantes.") com opção de retry após backoff. |
| **`502`** | `LLM_PROVIDER_ERROR` | Instabilidade transitória no provedor de LLM. *(Nota: a IA já executa 1 retry automático internamente antes de emitir este erro)*. | Repassar como indisponibilidade temporária do serviço de IA. |
| **`504`** | `LLM_TIMEOUT_ERROR` | Provedor de LLM não respondeu dentro de 30 segundos. | Orientar o usuário a tentar novamente. Certifique-se de que o timeout de leitura do Spring seja >= 35s. |
| **`422`** | *(FastAPI validation)* | Campo `texto` ausente, vazio ou formato JSON corrompido. | O Spring deve validar previamente com `@NotBlank` no DTO antes de despachar a chamada. |

---

## 6. Diagnóstico e Resolução de Problemas (Troubleshooting)

### 6.1 Testes Rápidos Sem Subir o Servidor HTTP
O repositório inclui um utilitário dedicado para diagnosticar credenciais e conectividade com o LLM:

```bash
# Smoke test (apenas testa autenticação e resposta rápida do LLM)
python scripts/test_llm_live.py --smoke

# Teste completo de interpretação direto no terminal
python scripts/test_llm_live.py "Comissão de 3.5% para vendedores da marca PRETO na loja 75 em outubro de 2026"
```

### 6.2 Teste Manual da Rota com cURL
```bash
curl -X POST "http://localhost:8000/api/v1/interpretar" \
  -H "Content-Type: application/json" \
  -d '{
    "texto": "Comissão de 4% para os gerentes na loja 12 em novembro",
    "contexto": {
      "ano_referencia": 2026,
      "dicionario_dimensoes": {
        "marcas": { "10": "PRETO" },
        "cargos": { "100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA" }
      }
    }
  }'
```

### 6.3 Teste Manual via PowerShell (Windows)
```powershell
$body = @{
    texto = "Comissão de 5% para vendedores da marca PRETO em dezembro de 2026"
    contexto = @{
        ano_referencia = 2026
        dicionario_dimensoes = @{
            marcas = @{ "10" = "PRETO" }
            cargos = @{ "100" = "VENDEDOR LOJA" }
        }
    }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/interpretar" -Method Post -ContentType "application/json" -Body $body
```

### 6.4 Problemas Comuns e Soluções

#### 1. Erro: `ImportError: SDK do Gemini não instalado. Execute: pip install google-genai`
- **Causa:** O SDK do provedor configurado não foi instalado no ambiente.
- **Solução Local:** Execute `pip install google-genai` (ou o SDK correspondente ao `LLM_PROVIDER`).
- **Solução Docker:** Reconstrua a imagem garantindo que `LLM_SDK` esteja configurado no build:
  ```bash
  docker compose build --no-cache
  ```

#### 2. Erro: `401 - LLM_AUTH_ERROR: Chave de API não configurada no ambiente`
- **Causa:** A variável `LLM_API_KEY` está vazia ou ausente no `.env`.
- **Solução:** Gere uma chave de API válida no Google AI Studio (ou provedor correspondente) e atualize o `.env`. Em seguida reinicie o serviço.

#### 3. Erro: `Connection Refused` ao chamar a partir do Spring em container
- **Causa:** O Spring está tentando conectar em `localhost:8000` em vez de apontar para o nome do serviço na rede Docker.
- **Solução:** Configure no Spring `ai.service.base-url=http://bugbusters-ai:8000` e certifique-se de que ambos os containers compartilham a mesma rede Docker (`network`).

---

## 7. Limitações e Premissas do MVP (Sprint 1) para o Manual S1-B14

Para compor a documentação da entrega e orientar os usuários e o time de desenvolvimento no manual **S1-B14**, observe as seguintes limitações e decisões de projeto aprovadas para a Sprint 1:

1. **Dependência de Catálogo de Dimensões:**
   - A IA resolve `codMarca` e `codCargo` exclusivamente cruzando os nomes citados no texto com o catálogo fornecido em `contexto.dicionario_dimensoes`.
   - Se o catálogo não for enviado pelo Spring, ou se a marca/cargo citada não existir no dicionário, os campos correspondentes retornam `null` com pendência explicativa em `pendencias`.

2. **Extração de Loja Sem Validação de Catálogo:**
   - No MVP da Sprint 1 não existe catálogo de lojas injetado.
   - O campo `codLoja` é extraído puramente por expressão numérica e contexto do texto (ex: *"loja 75"* $\rightarrow$ `75`). A validação de existência física da filial deve ser efetuada no backend Spring.

3. **Matrícula / Colaborador Individual Não Suportado:**
   - O MVP foca em regras por dimensão/segmento (marca, cargo, loja, canal).
   - Menções a colaboradores específicos (ex: *"para o funcionário 12345"*) não geram chave estruturada; a IA inclui um aviso na lista de `pendencias`.

4. **Vigência Flexível (`dataFim: null`):**
   - Quando o texto não expressar data de término (ex: *"comissão a partir de outubro"*), `dataFim` retorna deliberadamente como `null`.
   - Isso não constitui erro: cabe à lógica de negócio do Spring aplicar as regras padrão de vigência na criação do rascunho.

5. **Score de Confiança Determinístico:**
   - O campo `confianca` (0.00 a 1.00) não é uma alucinação ou "opinião" do LLM. Ele é calculado de forma transparente pelo serviço Python com base na completude dos campos essenciais e na presença de ambiguidades.

6. **Sem Efeito Colateral:**
   - O microsserviço de IA é puramente consultivo e analítico. Nenhuma regra é gravada, persistida ou ativada por ele.

---

## 8. Documentação Complementar

- [docs/CONTRATO-INTERPRETAR.md](./CONTRATO-INTERPRETAR.md): Especificação completa dos contratos JSON de entrada (`InterpretacaoRegraRequest`) e saída (`InterpretacaoRegraResponse`).
- [fluxo-ia-por-sprint.md](../fluxo-ia-por-sprint.md): Visão geral do ciclo de vida dos dados e arquitetura multi-sprint.
- [CONTRIBUTING.md](../CONTRIBUTING.md): Diretrizes para contribuição de código e execução de suítes de testes.
