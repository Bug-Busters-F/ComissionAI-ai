# Integração Spring ↔ Python — Contratos

## Princípio Geral

O Spring é o único cliente do serviço Python. O Spring:
1. Enriquece a requisição com catálogo do banco antes de chamar o Python
2. Valida tudo novamente após receber a resposta — não confia cegamente no Python
3. Salva propostas como **rascunho** (nunca ativa automaticamente)

## Endpoint de Interpretação (Sprint 1)

**`POST /interpretar`**

### Request (Spring → Python)

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

Campos obrigatórios no body:
- `texto` — linguagem natural digitada pelo gestor
- `data_referencia` — data de contexto (sem ela, "em dezembro" é indecidível)
- `catalogo` — catálogo completo fornecido pelo Spring (marcas, lojas, cargos)

### Response — Sucesso

```json
{
  "status": "ok",
  "operacao": "SUBSTITUIR_PERCENTUAL",
  "percentual": "0.0300",
  "publico": {
    "marca_codigo": null,
    "loja_codigo": 75,
    "cargo_codigo": 100,
    "matricula": null
  },
  "inicio": "2026-12-01",
  "fim": "2026-12-31",
  "pendencias": [],
  "texto_original": "3% para os vendedores da loja 75 em dezembro"
}
```

### Response — Pendências

```json
{
  "status": "pendencias",
  "pendencias": [
    {
      "campo": "loja_codigo",
      "motivo": "Loja 99 não encontrada no catálogo.",
      "pergunta": "Qual loja você quis dizer?"
    }
  ],
  "texto_original": "3% para os vendedores da loja 99 em dezembro"
}
```

### Response — Erros HTTP

| Status | Situação                                  |
|--------|-------------------------------------------|
| 422    | Body inválido (campos obrigatórios ausentes) |
| 503    | Provedor de LLM indisponível              |
| 504    | Timeout na chamada ao LLM                 |
| 500    | Erro interno inesperado                   |

## Campos do Schema `RegraInterpretada` (a definir em S1-A02)

| Campo          | Tipo          | Descrição                                         |
|----------------|---------------|---------------------------------------------------|
| `status`       | Enum          | `"ok"` ou `"pendencias"`                          |
| `operacao`     | Enum          | `SUBSTITUIR_PERCENTUAL`, `ACRESCENTAR_PONTO_PERCENTUAL`, etc. |
| `percentual`   | Decimal str   | Taxa decimal com 4 casas: `"0.0300"`              |
| `publico`      | Objeto        | `marca_codigo`, `loja_codigo`, `cargo_codigo`, `matricula` — null quando não especificado |
| `inicio`       | date str      | `"YYYY-MM-DD"`                                    |
| `fim`          | date str / null | `null` → Spring aplica default de 30 dias       |
| `pendencias`   | Lista         | Vazia quando `status = "ok"`                      |
| `texto_original` | str         | Texto exato enviado pelo gestor                   |

## Convenções de Formato

- Percentual: sempre `Decimal` com 4 casas decimais (`"0.0300"`, não `"3%"`)
- Datas: sempre `"YYYY-MM-DD"` (ISO 8601)
- Ausência de informação: `null` explícito (nunca omitir o campo)
- `fim: null` preserva a informação de que o gestor não especificou fim — o Spring aplica o default
