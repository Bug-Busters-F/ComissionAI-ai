# Sprint 1 — Interpretação de Regras

**Estado atual:** Sprint 1 em andamento.
O serviço Python é **stateless e sem tools** nesta sprint: entra texto/contexto, sai JSON de proposta de interpretação compatível com S1-B02. Uma chamada ao LLM, sem laço.

## Tasks da Sprint 1 (eixo AI)

| ID     | Task                                         | Status     |
|--------|----------------------------------------------|------------|
| S1-A01 | Estruturar base do repositório AI            | ✅ Concluída |
| S1-A02 | Definir esquema estruturado das regras       | ✅ Concluída |
| S1-A03 | Integrar provedor de LLM e framework         | ⬜ Pendente  |
| S1-A04 | Implementar interpretação de regras          | ⬜ Pendente  |
| S1-A05 | Implementar normalização de percentuais e datas | ⬜ Pendente |
| S1-A06 | Implementar validação da resposta do modelo  | ⬜ Pendente  |
| S1-A07 | Tratar regras ambíguas ou incompletas        | ⬜ Pendente  |
| S1-A08 | Disponibilizar endpoint de interpretação     | ⬜ Pendente  |
| S1-A09 | Integrar interpretação ao fluxo de cadastro  | ⬜ Pendente  |
| S1-A10 | Preparar execução e documentação do serviço  | ⬜ Pendente  |

## Fluxo Interno do Serviço (Sprint 1) — Cinco Etapas

### Etapa 1 — Montagem do Prompt (`core/`)
Você **monta** o prompt juntando os seguintes elementos:
1. O comando textual digitado pelo gestor (`texto`)
2. Metadados de contexto fornecidos pelo Backend (`contexto`, ex.: `ano_referencia`, `canal_padrao`)
3. Exemplos representativos (one-shot / few-shot), incluindo casos válidos e casos com pendências
4. A regra fundamental: *na dúvida ou informação ausente, aponte pendências descritivas; nunca invente dados ou parâmetros*

### Etapa 2 — Chamada ao LLM com saída estruturada (`providers/`)
Passar o JSON Schema gerado pelo Pydantic (`InterpretacaoRegraResponse.model_json_schema()`) ou instrução estruturada correspondente para garantir conformidade de formato.

### Etapa 3 — Validação Estrutural (Pydantic)
O Pydantic (`InterpretacaoRegraResponse`) valida:
- Campos suportados: `canal`, `taxa`, `dataInicio`, `dataFim`, `confianca`, `pendencias`
- Tipos de dados (`Decimal`, `date`, `list[str]`, etc.)
- Normalização automática de canal (`trim().upper()`)

### Etapa 4 — Normalização e Validação Semântica (`core/` e Pydantic)
- `taxa`: proporção decimal numérica no intervalo `0 < taxa <= 1.0000` (ex: `0.0500` para 5%)
- `dataInicio` / `dataFim`: formato ISO 8601 (`YYYY-MM-DD`)
- Validação temporal: `dataFim >= dataInicio` quando ambas forem fornecidas
- `dataFim: null` quando não especificada pelo gestor (o Backend aplicará o default de 30 dias na confirmação)
- `pendencias`: lista de strings detalhando ambiguidades ou dados essenciais ausentes

### Etapa 5 — Resposta ao Backend Spring Boot
Retorno do payload estruturado JSON compatível com o DTO `InterpretacaoRegraResponse`.

---

## Exemplo de Requisição (Spring → Python)

```json
{
  "texto": "Pagar 5% no canal ecommerce durante dezembro",
  "contexto": {
    "canal_padrao": "ECOMMERCE",
    "ano_referencia": 2026
  }
}
```

## Exemplo de Resposta Canônica (Python → Spring)

```json
{
  "canal": "ECOMMERCE",
  "taxa": 0.0500,
  "dataInicio": "2026-12-01",
  "dataFim": "2026-12-31",
  "confianca": 0.95,
  "pendencias": []
}
```

Se houver pendências (informações incompletas ou ambíguas):

```json
{
  "canal": null,
  "taxa": null,
  "dataInicio": null,
  "dataFim": null,
  "confianca": 0.30,
  "pendencias": [
    "Canal de vendas não identificado.",
    "Percentual de comissão não identificado.",
    "Data de início da vigência não identificada."
  ]
}
```

---

## O que NÃO implementar na Sprint 1

- Tool calling (laço LLM → Spring → LLM) — Sprint 2
- Simulação orçamentária — Sprint 2
- Detecção de anomalias — Sprint 3
- Persistência direta de regras pelo serviço Python — papel exclusivo do Spring Boot
- Campos ausentes no modelo de negócio S1-B02 (`publico`, `marca_codigo`, `loja_codigo`, `cargo_codigo`, `operacao`, `percentual`, etc.)
