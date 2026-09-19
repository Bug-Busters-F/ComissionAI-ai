# Sprint 1 — Interpretação de Regras

**Estado atual:** Sprint 1 em andamento.
O serviço Python é **stateless e sem tools** nesta sprint: entra texto/contexto, sai JSON de proposta de interpretação compatível com S1-B02. Uma chamada ao LLM, sem laço.

## Tasks da Sprint 1 (eixo AI)

| ID     | Task                                         | Status     |
|--------|----------------------------------------------|------------|
| S1-A01 | Estruturar base do repositório AI            | ✅ Concluída |
| S1-A02 | Definir esquema estruturado das regras       | ✅ Concluída |
| S1-A03 | Integrar provedor de LLM e framework         | ✅ Concluída |
| S1-A04 | Implementar interpretação de regras          | ✅ Concluída |
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
2. Catálogo de dimensões do banco (`dicionario_dimensoes`: marcas, cargos, canais) — formatado e injetado no prompt
3. Metadados de contexto (`ano_referencia`, `canal_padrao`)
4. Exemplos representativos (few-shot), incluindo casos válidos e com pendências
5. A regra fundamental: *na dúvida ou informação ausente, aponte pendências descritivas; nunca invente dados ou parâmetros*

### Etapa 2 — Chamada ao LLM com saída estruturada (`providers/`)
Passar o JSON Schema gerado pelo Pydantic (`InterpretacaoRegraRawLLM.model_json_schema()`) para garantir conformidade de formato.
O LLM extrai termos **brutos**: `canal`, `taxa_raw`, `vigencia_inicio_raw`, `vigencia_fim_raw`, `marca_raw`, `loja_raw`, `cargo_raw`.

### Etapa 3 — Validação Estrutural (Pydantic)
O Pydantic (`InterpretacaoRegraRawLLM`) valida os tipos dos dados brutos retornados pelo LLM.

### Etapa 4 — Normalização e Validação Semântica (`core/normalizers/`)
- `taxa`: proporção decimal numérica no intervalo `0 < taxa <= 1.0000`
- `dataInicio` / `dataFim`: formato ISO 8601 (`YYYY-MM-DD`)
- `canal`: normalizado em maiúsculas; opcional (nullable); se ausente e sem `canal_padrao`, retorna `null` sem pendência
- `marca_raw` → (`codMarca`, `descrMarca`): resolvido por match exato no catálogo `dicionario_dimensoes.marcas`
- `loja_raw` → `codLoja`: extraído como inteiro do texto
- `cargo_raw` → (`codCargo`, `descriCargo`): resolvido no catálogo `dicionario_dimensoes.cargos`. Se houver ambiguidade onde os candidatos compartilham o mesmo código (ex: 150 para `GERENTE DE LOJA` e `GERENTE QUIOSQUE`), retorna o código comum (`codCargo: 150`) e `descriCargo: null` com pendência descritiva. Se os códigos divergirem ou não houver match, retorna `null` para ambos com pendência.
- `confianca`: calculada deterministicamente considerando completude de taxa, vigência e escopo (canal, marca, cargo ou loja)

### Etapa 5 — Resposta ao Backend Spring Boot
Retorno do payload estruturado JSON compatível com o DTO `InterpretacaoRegraResponse`.

---

## Exemplo de Requisição (Spring → Python)

```json
{
  "texto": "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
  "contexto": {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
      "marcas": {"10": "PRETO", "20": "BRANCO"},
      "cargos": {"100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA"},
      "canais": ["LOJA_FISICA", "ECOMMERCE"]
    }
  }
}
```

## Exemplo de Resposta Canônica (Python → Spring)

```json
{
  "canal": "LOJA_FISICA",
  "codMarca": 10,
  "descrMarca": "PRETO",
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA",
  "codLoja": 75,
  "taxa": 0.0350,
  "dataInicio": "2026-10-01",
  "dataFim": "2026-10-31",
  "confianca": 0.95,
  "pendencias": []
}
```

Se houver pendências (informações incompletas ou ambíguas):

```json
{
  "canal": null,
  "codMarca": null,
  "descrMarca": null,
  "codCargo": null,
  "descriCargo": null,
  "codLoja": null,
  "taxa": null,
  "dataInicio": null,
  "dataFim": null,
  "confianca": 0.30,
  "pendencias": [
    "Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'.",
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
- `matricula` — fora do escopo da Sprint 1
- Campos legados (`publico`, `marca_codigo`, `loja_codigo`, `cargo_codigo`, `operacao`, `percentual`) — substituídos pelos campos individuais do contrato atual
