# Sprint 1 — Interpretação de Regras

**Estado atual:** Sprint 1 em andamento.
O serviço Python é **stateless e sem tools** nesta sprint: entra texto, sai JSON. Uma chamada ao LLM, sem laço.

## Tasks da Sprint 1 (eixo AI)

| ID     | Task                                         | Status     |
|--------|----------------------------------------------|------------|
| S1-A01 | Estruturar base do repositório AI            | ✅ Concluída |
| S1-A02 | Definir esquema estruturado das regras       | ⬜ Pendente  |
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
Você **monta** o prompt juntando quatro ingredientes:
1. O texto do gestor
2. O catálogo formatado como lista de valores permitidos (marcas, lojas, cargos)
3. Cinco a oito exemplos resolvidos, incluindo dois que terminam em pendência
4. A regra de ouro: *na dúvida, devolva pendência; nunca invente parâmetro*

> O catálogo no prompt é o que impede o modelo de inventar "marca ROXO". Ele só pode escolher entre o que foi listado.

### Etapa 2 — Chamada ao LLM com saída estruturada (`providers/`)
Não pedir "responda em JSON" e torcer. Passar o JSON Schema gerado pelo Pydantic
(`RegraInterpretada.model_json_schema()`) como `response_schema` — o provedor
obriga o modelo a respeitar o formato.

A resposta do LLM propositalmente chega "suja":
- `"3%"` ainda é string
- `"dezembro"` ainda não é data

Normalização é trabalho determinístico — código faz isso melhor e mais barato que LLM.

### Etapa 3 — Validação Estrutural (Pydantic)
O Pydantic checa: os campos existem? Os tipos batem? `operacao` é um valor válido do Enum?
Se algo estiver fora, levanta `ValidationError` — não deixa chegar na normalização.

### Etapa 4 — Normalização (`core/`)
- `"3%"` → `Decimal("0.0300")`
- `"dezembro"` + `data_referencia: 2026-09-07` → `2026-12-01` a `2026-12-31`
- `fim: null` continua `null` — é informação (o gestor não especificou fim); quem aplica o default de 30 dias é o Spring

### Etapa 5 — Validação Semântica (Pydantic `@model_validator`)
Confronta o resultado com o catálogo recebido:
- A loja citada existe no catálogo?
- Se o texto citou marca, ela bate com a loja?
- O percentual é plausível? (ex: 300% vira pendência)
- Combinações de dois campos: `ACRESCENTAR_PONTO_PERCENTUAL` + cargo ambíguo → pendência

Usa `@model_validator(mode="after")`, não `@field_validator` isolado.

## Exemplo de Requisição (Spring → Python)

```json
{
  "texto": "3% para os vendedores da loja 75 em dezembro",
  "data_referencia": "2026-09-07",
  "catalogo": {
    "marcas": [{"codigo": 10, "nome": "PRETO"}, {"codigo": 20, "nome": "BRANCO"}],
    "lojas":  [{"codigo": 75, "nome": "...", "marca_codigo": 20}],
    "cargos": [{"codigo": 100, "descricao": "vendedor de loja"}]
  }
}
```

## Exemplo de Resposta (Python → Spring)

```json
{
  "status": "ok",
  "operacao": "SUBSTITUIR_PERCENTUAL",
  "percentual": "0.0300",
  "publico": {"marca_codigo": null, "loja_codigo": 75, "cargo_codigo": 100, "matricula": null},
  "inicio": "2026-12-01",
  "fim": "2026-12-31",
  "pendencias": [],
  "texto_original": "3% para os vendedores da loja 75 em dezembro"
}
```

Se houver pendência, `status` é `"pendencias"` e o array traz o quê, o porquê e a pergunta a fazer ao usuário.

## O que NÃO implementar na Sprint 1

- Tool calling (laço LLM → Spring → LLM) — isso é Sprint 2
- Simulação orçamentária — Sprint 2
- Detecção de anomalias — Sprint 3
- Persistência de regras pelo serviço Python — nunca (é papel do Spring)
