# Arquitetura do Sistema — Regras Invariantes

Este documento descreve a arquitetura geral do sistema de Gerenciamento de Regras de Negócio
desenvolvido pelo time Bug Busters para a Dom Rock (6º semestre ADS — Fatec São José dos Campos).

## Visão Geral

O sistema é composto por três serviços principais:

- **Vue (front-end)** — interface do gestor
- **Spring Boot (back-end)** — fonte da verdade de negócio, cálculo e persistência
- **Python/FastAPI (serviço de IA)** — interpreta linguagem natural, devolve JSON estruturado

## As Três Regras que Nunca Mudam

### 1. O front NUNCA fala com o serviço de IA
O Vue só conhece o Spring. O Spring é quem chama o Python.
Se o front chamasse os dois, existiriam duas fontes de validação — nunca faça isso.

### 2. O serviço Python NÃO acessa banco de dados
Tudo que o serviço de IA precisa saber sobre a empresa chega na própria requisição
(catálogo de marcas, lojas, cargos). Isso mantém o serviço stateless — testável e reescritível.

### 3. O LLM NUNCA é fonte da verdade
O LLM preenche formulário e escolhe caminhos.
Quem decide o que é válido é a validação determinística (Pydantic).
Quem calcula dinheiro é o Spring.

## Fluxo de uma Requisição (Sprint 1)

```
Vue → Spring → Python → Spring → Vue
```

1. Vue envia texto livre ao Spring
2. Spring enriquece com catálogo do banco e chama Python
3. Python monta prompt, chama LLM, valida e normaliza
4. Python devolve JSON estruturado ao Spring
5. Spring valida novamente, salva como rascunho e devolve ao Vue
6. Vue exibe formulário pré-preenchido para revisão do gestor

## Responsabilidades por Serviço

| Responsabilidade          | Quem faz    |
|---------------------------|-------------|
| Calcular comissão         | Spring      |
| Persistir dados           | Spring      |
| Validar vínculos no banco | Spring      |
| Interpretar linguagem natural | Python  |
| Montar prompt             | Python      |
| Chamar LLM                | Python      |
| Validar estrutura do JSON | Python (Pydantic) |
| Normalizar percentual/data | Python     |
| Renderizar interface      | Vue         |

## Repositórios

- **Este repositório** — serviço Python (IA)
- Repositório principal (Spring + Vue): https://github.com/Bug-Busters-F/API-6
