# Integração Spring ↔ Python — Contratos e Regras (S1-B03 / S1-A02)

## 1. Princípio Geral e Fonte de Verdade

O modelo de negócio definido na **S1-B02 do repositório Backend é a fonte de verdade** (`model/Regra.java`, `dto/regra/RegraRequest.java`, `dto/regra/RegraResponse.java`, `dto/interpretador/InterpretacaoRegraRequest.java`, `dto/interpretador/InterpretacaoRegraResponse.java`, `service/InterpretadorService.java`, `service/client/AiServiceClient.java`, `db/migration/V1__criar_estrutura_mvp.sql`).

O **Backend Spring Boot** é o único cliente do serviço de IA Python. O serviço de IA **NÃO define, altera ou inventa campos do modelo de negócio**. Ele produz exclusivamente uma **proposta de regra estruturada** a partir de linguagem natural.

### Separação de Responsabilidades:
- **Serviço de IA (Python)**:
  - Interpreta o texto em linguagem natural e o contexto fornecido.
  - Usa o catálogo `dicionario_dimensoes` para resolver marcas, cargos e canais por nome.
  - Normaliza os valores (canal em caixa alta, taxa em formato decimal, datas em ISO 8601).
  - Identifica ambiguidades e aponta pendências em lista de strings (`pendencias: List[str]`).
  - Retorna a proposta estruturada para o Backend.
  - **NÃO**: cria `id`, define `status`, associa `campanha`, define auditoria, grava no banco ou ativa regras diretamente.
- **Backend (Spring Boot)**:
  - Aplica princípio de **Zero Trust** (validação defensiva rigorosa sobre a resposta da IA).
  - Enriquece o request com o catálogo de marcas, cargos e canais do banco de dados.
  - Aplica regras de negócio complementares no fluxo de confirmação (ex.: vigência padrão de 30 dias quando `dataFim` for `null`).
  - Constrói a entidade `Regra`, define status, vínculos e persiste no banco de dados.

---

## 2. Endpoint de Interpretação (Sprint 1)

**`POST /api/v1/interpretar`**

> **Escopo de Tasks:** No repositório de IA, o contrato está definido nos schemas (`app/schemas/regra.py` — S1-A02) e implementado no serviço orquestrador (`InterpretadorRegraService` — S1-A04). A exposição da rota HTTP no FastAPI (`api/routes/interpretador.py`) pertence à task **S1-A08** e será disponibilizada em sua respectiva etapa.

---

## 3. Request (Backend Spring → IA Python)

O Backend envia o comando textual e o catálogo com as dimensões conhecidas do banco.

```json
{
  "texto": "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
  "contexto": {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
      "marcas": {
        "10": "PRETO",
        "20": "BRANCO",
        "30": "AZUL",
        "40": "VERMELHO",
        "50": "AMARELO",
        "60": "CINZA"
      },
      "cargos": {
        "100": "VENDEDOR LOJA",
        "150": "GERENTE DE LOJA",
        "200": "VENDEDOR BALCAO",
        "300": "ASSISTENTE DE VENDAS"
      },
      "canais": ["LOJA_FISICA", "ECOMMERCE", "BALCAO", "QUIOSQUE", "APP", "PADRAO"]
    }
  }
}
```

### Campos do Request:
| Campo | Tipo | Obrigatório | Descrição |
|---|---|:---:|---|
| `texto` | `String` | **Sim** | Comando em linguagem natural digitado pelo gestor. |
| `contexto` | `Map<String, Object>` / `dict` | Não | Metadados contextuais opcionais. A ausência de chaves **não autoriza a IA a inventar valores**. |
| `contexto.ano_referencia` | `Integer` | Não | Ano de referência para resolução de meses sem ano explícito. |
| `contexto.dicionario_dimensoes` | `Object` | Não | Catálogo de marcas, cargos e canais disponíveis no banco. |
| `contexto.dicionario_dimensoes.marcas` | `Map<String, String>` | Não | Mapa código → nome da marca (ex: `{"10": "PRETO"}`). |
| `contexto.dicionario_dimensoes.cargos` | `Map<String, String>` | Não | Mapa código → nome do cargo (ex: `{"100": "VENDEDOR LOJA"}`). |
| `contexto.dicionario_dimensoes.canais` | `List<String>` | Não | Lista de canais disponíveis (ex: `["LOJA_FISICA", "ECOMMERCE"]`). |

---

## 4. Response Canônica (IA Python → Backend Spring)

A IA retorna uma proposta de interpretação estruturada compatível com o DTO `InterpretacaoRegraResponse` do Backend:

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

### Campos da Resposta:
| Campo | Tipo Lógico / Backend | Obrigatório na Regra Válida | Comportamento na Interpretação da IA |
|---|---|:---:|---|
| `canal` | `String` / `null` | Não (nullable) | Canal de venda normalizado em maiúsculas. **Opcional** — `tb_regra.canal` é nullable desde a Correção 2 do banco. Não pode ser inferido como marca ou loja. Se omitido no texto e sem canal_padrao no contexto, retorna `null` sem gerar pendência. |
| `codMarca` | `Integer` / `null` | Não | Código numérico da marca resolvido pelo catálogo. `null` se não mencionada. |
| `descrMarca` | `String` / `null` | Não | Nome da marca em maiúsculas. Preenchido em conjunto com `codMarca`. |
| `codCargo` | `Integer` / `null` | Não | Código numérico do cargo resolvido pelo catálogo. Quando o termo for ambíguo mas os cargos compartilharem o mesmo código numérico (ex: 150 para GERENTE DE LOJA e GERENTE QUIOSQUE no Cenário C), retorna o código comum (150) e deixa `descriCargo: null` com pendência descritiva. `null` se os candidatos tiverem códigos divergentes ou se não mencionado. |
| `descriCargo` | `String` / `null` | Não | Descrição da função. Preenchido em conjunto com `codCargo` quando a função for unívoca. Retorna `null` se o cargo for ambíguo ou não mencionado. |
| `codLoja` | `Integer` / `null` | Não | Código numérico da loja extraído do texto. `null` se não mencionada. |
| `taxa` | `BigDecimal` / `null` | **Sim** | Proporção decimal `0 < taxa <= 1.0000`. Ex.: `0.0350` = 3,5%. |
| `dataInicio` | `LocalDate` / `null` | **Sim** | Data de início no formato `YYYY-MM-DD`. |
| `dataFim` | `LocalDate` / `null` | Não | Data de término. `null` se não especificada pelo gestor. |
| `confianca` | `BigDecimal` / `null` | Não | Score técnico da IA (0.00 a 1.00). Calculado deterministicamente considerando completude de taxa, vigência e escopo (canal, marca, cargo ou loja). Não persistido em `Regra`. |
| `pendencias` | `List<String>` | **Sim** | Lista de pendências/ambiguidades. `[]` quando a interpretação for completa. |

---

## 5. Mapeamento IA ↔ Backend

| Campo Resposta IA | Campo Entidade Backend (`Regra`) | Tipo Backend | Observação |
|---|---|---|---|
| `canal` | `Regra.canal` | `String` |  Nome do canal |
| `codMarca` | `Regra.codMarca` | `Integer` | Código numérico da marca |
| `descrMarca` | `Regra.descrMarca` | `String` | Nome da marca |
| `codCargo` | `Regra.codCargo` | `Integer` | Código numérico do cargo |
| `descriCargo` | `Regra.descriCargo` | `String` | Descrição do cargo |
| `codLoja` | `Regra.codLoja` | `Integer` | Código numérico da loja |
| `taxa` | `Regra.taxa` | `BigDecimal` | Proporção decimal (`0 < taxa <= 1.0000`) |
| `dataInicio` | `Regra.dataInicio` | `LocalDate` | Data inicial da vigência |
| `dataFim` | `Regra.dataFim` | `LocalDate` | Data final da vigência (`null` na IA → default 30 dias no Backend na confirmação) |
| `confianca` | — | `BigDecimal` | Metadado técnico de interpretação (não persistido em `Regra`) |
| `pendencias` | — | `List<String>` | Validação e apontamento de pendências para o gestor |

---

## 6. Campos que NÃO pertencem ao contrato de resposta da IA

Os seguintes campos **NÃO fazem parte do contrato de resposta da IA** e não devem ser retornados pelo serviço Python:
- `operacao` (ex.: `"SUBSTITUIR_PERCENTUAL"`) — não existe na entidade `Regra` nem no DTO.
- `percentual` — o campo canônico e oficial é `taxa` (número decimal, não String).
- `publico` (`marca_codigo`, `loja_codigo`, `cargo_codigo`, `matricula`) — campo legado, substituído pelos campos individuais `codMarca`, `codLoja`, `codCargo`.
- `inicio` / `fim` — os nomes canônicos são `dataInicio` e `dataFim`.
- `status` — gerido exclusivamente pelo Backend.
- `id`, `campanha_id`, `criadoEm`, `atualizadoEm`, `removidoEm` — geridos pelo Backend / Banco de Dados.
- `texto_original` — não pertence ao contrato de resposta do interpretador.
- `matricula` — fora do escopo da Sprint 1.

---

## 7. Exemplos de Contrato

### 7.1 Cenário A — Regra Completa com Marca, Cargo e Loja
**Entrada (Request):**
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
**Saída da IA (Response):**
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

### 7.2 Cenário B — Data Final Não Especificada (`dataFim: null`)
**Entrada (Request):**
```json
{
  "texto": "Pagar 5% no canal ecommerce a partir de 01/10/2026",
  "contexto": { "ano_referencia": 2026 }
}
```
**Saída da IA (Response):**
```json
{
  "canal": "ECOMMERCE",
  "codMarca": null,
  "descrMarca": null,
  "codCargo": null,
  "descriCargo": null,
  "codLoja": null,
  "taxa": 0.0500,
  "dataInicio": "2026-10-01",
  "dataFim": null,
  "confianca": 0.90,
  "pendencias": []
}
```
*(Nota: No Backend, o `InterpretadorService` adiciona a pendência informativa `"Data final omitida; serão aplicados 30 dias de vigência padrão na confirmação."`)*

### 7.3 Cenário C — Ambiguidade de Cargo (`codCargo: null`, pendência)
**Entrada (Request):**
```json
{
  "texto": "Pagar comissão especial para os gerentes",
  "contexto": { "ano_referencia": 2026 }
}
```
**Saída da IA (Response):**
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
*(Nota: `canal: null` e `codCargo: null` são respostas válidas para interpretação incompleta. O Backend registra pendências adicionais e aguarda confirmação do gestor.)*

---

## 8. Tratamento de Erros HTTP

| Status HTTP | Origem | Motivo |
|---|---|---|
| `200 OK` | IA Python | Regra interpretada com sucesso (inclui propostas com `pendencias`). |
| `400 Bad Request` | Backend / IA | Texto vazio ou JSON mal formatado. |
| `422 Unprocessable Entity` | IA Python | Erro de validação dos tipos no schema do request. |
| `503 Service Unavailable` | Backend (`AiServiceClient`) | Serviço de IA offline ou indisponível. |
| `504 Gateway Timeout` | Backend (`AiServiceClient`) | Timeout na resposta da LLM. |
