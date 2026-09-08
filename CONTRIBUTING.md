# Como Contribuir - Seu Passaporte de Entrada

Estamos felizes em receber você aqui e saber que está interessado em contribuir para o nosso projeto. Cada contribuição é valorizada e ajuda a melhorar a qualidade do nosso trabalho. Este guia apresenta orientações gerais para participar da nossa comunidade de desenvolvimento.

## Código de Conduta

Para garantir um ambiente respeitoso e inclusivo, leia e siga nosso [Código de Conduta](./CODE_OF_CONDUCT.md).

## Começando a Contribuir

Para começar, você precisará de:

- Uma conta no [GitHub](https://github.com/).
- O sistema de controle de versão [Git](https://git-scm.com/) instalado.
- Um editor de código ou IDE de sua preferência.
- As ferramentas e dependências exigidas pelo repositório, conforme sua documentação, quando disponível.

Você pode contribuir corrigindo problemas, implementando melhorias, escrevendo testes ou aprimorando a documentação. Antes de iniciar, consulte as issues e os pull requests existentes para evitar trabalho duplicado. Para mudanças maiores, abra uma issue para discutir a proposta com a equipe.

## Preparando o Ambiente

### 1. Clonar o Repositório

Na página do repositório no GitHub, copie a URL de clonagem. No terminal, execute os comandos abaixo, substituindo os valores entre `<>` pelos dados correspondentes:

```bash
git clone <URL_DO_REPOSITORIO>
cd <NOME_DO_REPOSITORIO>
```

Se você não tiver permissão de escrita, crie um fork no GitHub e clone o seu fork.

### 2. Configurar o Projeto

Consulte o README e a documentação do repositório, quando disponíveis, para instalar as dependências, configurar as variáveis de ambiente e executar o projeto. Os requisitos e comandos podem variar entre os repositórios.

Não inclua senhas, tokens ou outras informações sensíveis nos arquivos versionados. Se houver um arquivo de exemplo de variáveis de ambiente, use-o como referência para sua configuração local.

## Serviço AI (Python)

### Pré-requisitos

- Python 3.12 ou superior
- Chave de API do provedor de LLM escolhido (Gemini, OpenAI ou Anthropic)

### Instalação

```bash
# 1. Criar e ativar ambiente virtual
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

# 2. Instalar dependências base
pip install -r requirements.txt

# 3. Instalar o SDK do provedor de LLM que você vai usar (escolha um)
pip install google-generativeai   # Gemini
pip install openai                # OpenAI
pip install anthropic             # Anthropic
```

### Variáveis de Ambiente

Copie o arquivo de exemplo e preencha com suas credenciais:

```bash
cp .env.example .env
```

Edite o `.env` com os valores corretos:

| Variável       | Descrição                                           | Exemplo               |
|----------------|-----------------------------------------------------|-----------------------|
| `LLM_PROVIDER` | Provedor de LLM a usar                              | `gemini`              |
| `LLM_API_KEY`  | Chave de API do provedor                            | `AIza...`             |
| `LLM_MODEL`    | Modelo específico (deixe vazio para usar o default) | `gemini-1.5-flash`    |
| `APP_PORT`     | Porta em que o serviço sobe                         | `8000`                |
| `APP_RELOAD`   | Hot reload para desenvolvimento                     | `true`                |

> **Nunca versione o arquivo `.env`.** Ele já está no `.gitignore`.

### Inicialização Local

```bash
# A partir da raiz do repositório, com o venv ativo:
python -m uvicorn app.main:app --reload --app-dir src
```

O serviço estará disponível em `http://localhost:8000`.
Documentação interativa (Swagger): `http://localhost:8000/docs`
Health check: `http://localhost:8000/health`

### Execução via Docker

#### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) instalado e em execução
- [Docker Compose](https://docs.docker.com/compose/install/) (já incluído no Docker Desktop)

#### Configurar variáveis de ambiente

O `.env` é obrigatório antes de subir o container (o `.dockerignore` garante que ele não entre na imagem):

```bash
cp .env.example .env
# edite o .env com sua LLM_API_KEY e LLM_PROVIDER
```

#### Subir o serviço

```bash
# Construir a imagem e iniciar o container
docker compose up --build

# Ou em segundo plano (modo detached)
docker compose up --build -d
```

O serviço estará disponível em `http://localhost:8000`.
Documentação interativa (Swagger): `http://localhost:8000/docs`
Health check: `http://localhost:8000/health`

#### Hot reload durante o desenvolvimento

Para que alterações em `src/` sejam refletidas sem rebuildar a imagem, descomente o bloco `volumes` e `command` no `docker-compose.yml`:

```yaml
volumes:
  - ./src:/api/src
command: >
  python -m uvicorn app.main:app
  --host 0.0.0.0 --port 8000
  --app-dir src --reload
```

E então suba normalmente com `docker compose up`.

#### Comandos úteis

```bash
# Ver logs em tempo real
docker compose logs -f ai

# Parar e remover o container
docker compose down

# Acessar o shell do container
docker compose exec ai bash

# Rebuildar a imagem após mudar requirements.txt
docker compose up --build
```

## Enviando uma Contribuição

1. Crie uma branch para sua alteração:

   ```bash
   git switch -c tipo/descricao-da-alteracao
   ```

2. Faça alterações focadas no objetivo da contribuição, seguindo os padrões existentes no projeto.
3. Verifique o funcionamento da alteração e execute os testes e verificações disponíveis. Atualize a documentação quando necessário.
4. Revise os arquivos alterados e crie um commit com uma mensagem clara:

   ```bash
   git status
   git add <ARQUIVOS_ALTERADOS>
   git commit -m "Descreve a alteração realizada"
   ```

5. Envie sua branch para o GitHub:

   ```bash
   git push -u origin tipo/descricao-da-alteracao
   ```

6. Abra um pull request para a branch padrão do repositório original. Explique o que mudou, o motivo da mudança e como você validou o resultado. Relacione a issue correspondente, se houver.
7. Acompanhe a revisão e converse com a equipe sobre os ajustes solicitados.

## Relatando Problemas e Sugerindo Melhorias

Ao abrir uma issue, use um título claro e descreva o contexto. Para problemas, informe os passos para reproduzir, o comportamento esperado e o observado. Para melhorias, explique a necessidade e o resultado desejado.

---

Equipe Bug Busters
