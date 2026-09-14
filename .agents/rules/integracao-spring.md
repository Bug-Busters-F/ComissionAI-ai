# Integração Spring ↔ Python — Contratos e Regras (S1-B02 / S1-A02)

## 1. Princípio Geral e Fonte de Verdade

O modelo de negócio definido na **S1-B02 do repositório Backend é a fonte de verdade** (`model/Regra.java`, `dto/regra/RegraRequest.java`, `dto/regra/RegraResponse.java`, `dto/interpretador/InterpretacaoRegraRequest.java`, `dto/interpretador/InterpretacaoRegraResponse.java`, `service/InterpretadorService.java`, `service/client/AiServiceClient.java`, `db/migration/V1__criar_estrutura_mvp.sql`).

O **Backend Spring Boot** é o único cliente do serviço de IA Python. O serviço de IA **NÃO define, altera ou inventa campos do modelo de negócio**. Ele produz exclusivamente uma **proposta de regra estruturada** a partir de linguagem natural.

### Separação de Responsabilidades:
- **Serviço de IA (Python)**:
  - Interpreta o texto em linguagem natural e o contexto fornecido.
  - Normaliza os valores (canal em caixa alta, taxa em formato decimal, datas em ISO 8601).
  - Identifica ambiguidades e aponta pendências em lista de strings (`pendencias: List[str]`).
  - Retorna a proposta estruturada para o Backend.
  - **NÃO**: cria `id`, define `status`, associa `campanha`, define auditoria (`criadoEm`, `atualizadoEm`, `removidoEm`), grava no banco de dados ou ativa regras diretamente.
- **Backend (Spring Boot)**:
  - Aplica princípio de **Zero Trust** (validação defensiva rigorosa sobre a resposta da IA).
  - Aplica regras de negócio complementares no fluxo de confirmação (ex.: aplicação de 30 dias de vigência padrão quando `dataFim` for `null`).
  - Gerencia pendências e interação com o usuário/gestor.
  - Constrói a entidade `Regra`, define status, vínculos e persiste no banco de dados.

---

## 2. Endpoint de Interpretação (Sprint 1)

**`POST /interpretar`**

---

## 3. Request (Backend Spring → IA Python)

O Backend envia o comando textual em linguagem natural e metadados contextuais opcionais (`InterpretacaoRegraRequest`).

```json
{
  "texto": "Pagar 5% no canal ecommerce durante dezembro",
  "contexto": {
    "canal_padrao": "ECOMMERCE",
    "ano_referencia": 2026
  }
}
```

### Campos do Request:
| Campo | Tipo | Obrigatório | Descrição |
|---|---|:---:|---|
| `texto` | `String` | **Sim** | Comando em linguagem natural digitado pelo gestor. |
| `contexto` | `Map<String, Object>` / `dict` | Não | Metadados contextuais opcionais (ex.: `ano_referencia`, `canal_padrao`). A ausência de chaves **não autoriza a IA a inventar valores**. |

---

## 4. Response Canônica (IA Python → Backend Spring)

A IA retorna uma proposta de interpretação estruturada compatível com o DTO `InterpretacaoRegraResponse` do Backend:

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

### Campos da Resposta:
| Campo | Tipo Lógico / Backend | Obrigatório na Regra Válida | Comportamento na Interpretação da IA |
|---|---|:---:|---|
| `canal` | `String` (`String` / `null`) | **Sim** | Obrigatório para uma regra válida persistida. Durante a interpretação, pode ser `null` caso a IA não consiga identificá-lo no texto/contexto (o Backend registrará pendência). Quando presente, deve ser normalizado com `trim().toUpperCase()` (ex.: `"ECOMMERCE"`, `"LOJA_FISICA"`, `"WHATSAPP"` — sem enumeração fechada). Não pode ser inferido como marca ou loja. |
| `taxa` | `BigDecimal` (número decimal JSON) | **Sim** | Obrigatório para uma regra válida. Representado como **número decimal JSON** (ex.: `0.0500`), refletindo o tipo `BigDecimal` do Backend com precisão de até 4 casas decimais. Pode ser `null` se não identificado (gerando pendência). Deve satisfazer `0 < taxa <= 1.0000`.<br>• `0.0500` = 5%<br>• `0.0300` = 3%<br>• `1.0000` = 100%<br>• **Nunca** usar `5` para 5% nem `"5%"` (String).<br>*Nota: A representação JSON de números não garante a preservação semântica de zeros à direita, mas o valor continua sendo estritamente decimal.* |
| `dataInicio` | `LocalDate` (`YYYY-MM-DD` / `null`) | **Sim** | Obrigatório para uma regra válida. Durante a interpretação, pode ser `null` caso a IA não consiga identificar a data no texto ou contexto. Quando for `null`, o Backend registra uma pendência (o `InterpretadorService` atual **não** atribui data atual automaticamente). Formato ISO 8601 (`YYYY-MM-DD`). |
| `dataFim` | `LocalDate` (`YYYY-MM-DD` / `null`) | Não | Data final da vigência (`YYYY-MM-DD`). Se o gestor não especificou explicitamente, a IA deve retornar `null`. A IA **não deve inventar** uma data final. Ao receber `dataFim: null`, o Backend registra a pendência informativa de que serão aplicados 30 dias de vigência padrão na confirmação. |
| `confianca` | `BigDecimal` (número decimal JSON / `null`) | Não | **Metadado técnico da integração** presente no DTO `InterpretacaoRegraResponse` (ex.: `0.95`). Não é campo da entidade `Regra`, não é regra de negócio de comissão e não deve ser confundido com dados para persistência da regra. |
| `pendencias` | `List<String>` | **Sim** | Lista de mensagens textuais apontando problemas, dados ausentes ou ambiguidades. Deve ser `[]` quando a interpretação de todos os campos obrigatórios for completa e inequívoca. |

---

## 5. Mapeamento IA ↔ Backend

| Campo Resposta IA | Campo Entidade Backend (`Regra`) | Tipo Backend | Observação |
|---|---|---|---|
| `canal` | `Regra.canal` | `String` | Normalizado em maiúsculas (`trim().toUpperCase()`) |
| `taxa` | `Regra.taxa` | `BigDecimal` | Proporção decimal (`0 < taxa <= 1.0000`) |
| `dataInicio` | `Regra.dataInicio` | `LocalDate` | Data inicial da vigência |
| `dataFim` | `Regra.dataFim` | `LocalDate` | Data final da vigência (`null` na IA → default 30 dias no Backend na confirmação) |
| `confianca` | — | `BigDecimal` | Metadado técnico de interpretação (não persistido em `Regra`) |
| `pendencias` | — | `List<String>` | Validação e apontamento de pendências para o gestor |

---

## 6. Campos que NÃO pertencem ao contrato de resposta da IA

Os seguintes campos **NÃO fazem parte do contrato de resposta da IA** e não devem ser retornados pelo serviço Python:
- `operacao` (ex.: `"SUBSTITUIR_PERCENTUAL"`) — não existe na entidade `Regra` nem no DTO.
- `percentual` — o campo canônico e oficial é `taxa` (e como número decimal, não String).
- `publico` (`marca_codigo`, `loja_codigo`, `cargo_codigo`, `matricula`) — não faz parte do modelo MVP de `Regra`.
- `inicio` / `fim` — os nomes canônicos são `dataInicio` e `dataFim`.
- `status` — gerido exclusivamente pelo Backend.
- `id`, `campanha_id`, `criadoEm`, `atualizadoEm`, `removidoEm` — geridos pelo Backend / Banco de Dados.
- `texto_original` — **não pertence ao contrato de resposta do interpretador**. O Backend recebe `texto` no request e pode tratar ou armazenar o texto original separadamente se necessário, mas a resposta da IA não deve conter esse campo.

---

## 7. Exemplos de Contrato

### 7.1 Interpretação Completa com Vigência Fechada
**Entrada (Request):**
```json
{
  "texto": "Pagar 5% no canal ecommerce durante dezembro",
  "contexto": {
    "ano_referencia": 2026
  }
}
```
**Saída da IA (Response):**
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

### 7.2 Data Final Não Especificada (`dataFim: null`)
**Entrada (Request):**
```json
{
  "texto": "Pagar 5% no canal ecommerce a partir de 01/10/2026",
  "contexto": {}
}
```
**Saída da IA (Response):**
```json
{
  "canal": "ECOMMERCE",
  "taxa": 0.0500,
  "dataInicio": "2026-10-01",
  "dataFim": null,
  "confianca": 0.90,
  "pendencias": []
}
```
*(Nota: No Backend, o `InterpretadorService` adiciona a pendência informativa `"Data final omitida; serão aplicados 30 dias de vigência padrão na confirmação."`. A aplicação dos 30 dias de vigência padrão ocorre no fluxo de confirmação gerenciado pelo Backend).*

### 7.3 Informações Insuficientes ou Ambíguas
**Entrada (Request):**
```json
{
  "texto": "Pagar uma comissão especial",
  "contexto": {}
}
```
**Saída da IA (Response):**
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
*(Nota: `canal: null` e `dataInicio: null` são respostas estruturalmente válidas para interpretação incompleta, gerando pendências no Backend, mas não constituem uma regra válida para confirmação direta).*

---

## 8. Tratamento de Erros HTTP

| Status HTTP | Situação |
|---|---|
| `422 Unprocessable Entity` | Body inválido, schema JSON incompatível ou campos obrigatórios ausentes no request. |
| `503 Service Unavailable` | Provedor de LLM indisponível / falha de conexão com a API externa. |
| `504 Gateway Timeout` | Timeout na resposta do modelo de IA. |
| `500 Internal Server Error` | Erro interno inesperado no serviço Python. |
