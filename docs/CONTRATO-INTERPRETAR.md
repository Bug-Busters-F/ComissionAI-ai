# Contrato — `POST /api/v1/interpretar`

Documento pro time de backend (Spring). Explica o que a rota de interpretação recebe,
o que devolve, e o que cada campo significa. Fonte da verdade: `src/app/schemas/regra.py`.

---

## Rota

```
POST /api/v1/interpretar
Content-Type: application/json
```

Implementação: `src/app/api/routes/interpretador.py`.

---

## O que ela recebe (`InterpretacaoRegraRequest`)

```json
{
  "texto": "Comissão de 3.5% para os vendedores da marca PRETO na loja 75 durante todo o mês de outubro de 2026",
  "contexto": {
    "ano_referencia": 2026,
    "dicionario_dimensoes": {
      "marcas": { "10": "PRETO", "20": "BRANCO" },
      "cargos": { "100": "VENDEDOR LOJA", "150": "GERENTE DE LOJA" },
      "canais": ["LOJA_FISICA", "ECOMMERCE"]
    }
  }
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `texto` | `string` | Sim | Comando em linguagem natural digitado pelo gestor. Não pode ser vazio nem só espaços (validado — retorna `422` se violar). |
| `contexto` | `object` | Não (default `{}`) | Metadados que só o Spring sabe (vêm do banco). |
| `contexto.ano_referencia` | `int` | Recomendado | Ano usado pra resolver datas relativas (ex: "em dezembro" → precisa saber de qual ano). Sem ele, usa o ano corrente da máquina do serviço de IA. |
| `contexto.canal_padrao` | `string` | Não | Canal a usar se o texto não mencionar nenhum e não for possível inferir. |
| `contexto.dicionario_dimensoes` | `object` | Recomendado | Catálogo pra IA validar/normalizar contra dados reais. Sem ele, a IA não consegue resolver `codMarca`/`codCargo` a partir do nome — eles voltam `null`. |
| `contexto.dicionario_dimensoes.marcas` | `{codigo: nome}` | — | Ex: `{"10": "PRETO"}`. |
| `contexto.dicionario_dimensoes.cargos` | `{codigo: nome}` | — | Ex: `{"100": "VENDEDOR LOJA"}`. |
| `contexto.dicionario_dimensoes.canais` | `string[]` | — | Ex: `["LOJA_FISICA", "ECOMMERCE"]`. |

> **Não existe catálogo de lojas.** `codLoja` é extraído só como número do texto (ex: "loja 75" → `75`), sem validar se aquela loja existe de verdade. Se isso vier a ser necessário, precisa adicionar `dicionario_dimensoes.lojas` aqui.

---

## O que ela devolve (`InterpretacaoRegraResponse`)

**Sucesso (200):**
```json
{
  "canal": null,
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

**Com pendências (ainda 200 — não é erro, é proposta incompleta):**
```json
{
  "canal": null,
  "codMarca": null,
  "descrMarca": null,
  "codCargo": 150,
  "descriCargo": null,
  "codLoja": null,
  "taxa": null,
  "dataInicio": null,
  "dataFim": null,
  "confianca": 0.30,
  "pendencias": [
    "Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'.",
    "Percentual de comissão não identificado."
  ]
}
```

| Campo | Tipo | Pode ser `null`? | Descrição |
|---|---|---|---|
| `canal` | `string` | Sim | Canal de venda normalizado em caixa alta (ex: `ECOMMERCE`). É uma dimensão independente — nunca é inferido a partir de marca/loja. |
| `codMarca` | `int` | Sim | Código numérico da marca, resolvido contra o catálogo enviado. `null` se não mencionada ou não encontrada. |
| `descrMarca` | `string` | Sim | Nome da marca em maiúsculas, resolvido junto com `codMarca`. |
| `codCargo` | `int` | Sim | Código do cargo. **Atenção:** pode vir preenchido mesmo com `descriCargo=null` — isso indica ambiguidade (dois cargos diferentes compartilham o mesmo código numérico, ex: 150 = "GERENTE DE LOJA" ou "GERENTE QUIOSQUE"). Nesse caso sempre vem acompanhado de uma pendência em `pendencias`. |
| `descriCargo` | `string` | Sim | Descrição do cargo, resolvida junto com `codCargo`. |
| `codLoja` | `int` | Sim | Código numérico da loja, extraído do texto. Não validado contra catálogo (não existe um). |
| `taxa` | `decimal` | Sim | Taxa de comissão já convertida pra decimal (`5%` → `0.0500`). Garantido `0 < taxa ≤ 1.0000` quando não-nulo. |
| `dataInicio` | `date` (`YYYY-MM-DD`) | Sim | Início da vigência. |
| `dataFim` | `date` (`YYYY-MM-DD`) | Sim | Fim da vigência. **`null` é informação, não erro** — significa que o gestor não especificou fim. Quem decide o default (hoje, +30 dias) é o Spring, não a IA. |
| `confianca` | `decimal` (0.00–1.00) | Sim | Score técnico calculado deterministicamente (não é o LLM que decide). Reflete completude dos campos e quantidade de pendências/ambiguidades. Não é campo de negócio — não precisa ser persistido. |
| `pendencias` | `string[]` | Nunca (mínimo `[]`) | Lista de textos legíveis descrevendo ambiguidades, campos faltando ou critérios fora do MVP (ex: "categoria de produto", "matrícula individual"). Front deve exibir isso pro usuário revisar antes de salvar. |

### Campos que a IA **nunca** devolve

- `matricula` — fora do escopo da Sprint 1. Se o texto mencionar um funcionário específico, isso vira uma entrada em `pendencias` (`criterios_nao_suportados`), não um campo estruturado.
- `status`, `id`, `campanha_id`, `criadoEm`, `atualizadoEm`, `removidoEm`, `texto_original` — controlados exclusivamente pelo Spring/banco. A IA nunca decide isso.

---

## Respostas de erro

Todas seguem o mesmo formato:
```json
{ "detail": "mensagem legível", "error_code": "LLM_XXX_ERROR" }
```

| HTTP | `error_code` | Quando acontece | O que o Spring deve fazer |
|---|---|---|---|
| `401` | `LLM_AUTH_ERROR` | Chave de API do provedor (Gemini/OpenAI/Anthropic) inválida ou ausente | Não é erro do usuário — alertar time/infra, não expor ao front como se fosse culpa do texto digitado |
| `429` | `LLM_RATE_LIMIT_ERROR` | Cota/limite de requisições do provedor excedido | Pode tentar de novo mais tarde; não é permanente |
| `502` | `LLM_PROVIDER_ERROR` | Falha interna/indisponibilidade transitória do provedor de LLM (ex: "alta demanda"). **A IA já tenta 1 retry automático antes de devolver esse erro** — se chegou até o Spring, os dois tentativas falharam. | Pode repassar como falha temporária pro front tentar de novo |
| `504` | `LLM_TIMEOUT_ERROR` | O provedor não respondeu dentro de `LLM_TIMEOUT_SECONDS` (hoje 30s) | Verificar se o `AI_READ_TIMEOUT` do Spring está com folga suficiente acima disso (hoje 35s) |
| `422` | (padrão FastAPI) | `texto` vazio/só espaços, ou payload malformado | Erro de validação — o Spring já valida `@NotBlank` antes de chamar, então isso não deveria acontecer no fluxo normal |

---

## Coisas que **não** são responsabilidade dessa rota

- Não persiste nada no banco.
- Não ativa regra nenhuma — só devolve uma proposta pra revisão humana.
- Não decide o default de `dataFim` (isso é do Spring, na hora de salvar como rascunho).
- Não valida se a loja existe de verdade (sem catálogo de lojas disponível hoje).
