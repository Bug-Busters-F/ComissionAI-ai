# IA-7 — Explicações com números verificáveis

`POST /api/v2/simular` devolve `explicacoes[]`, com uma entrada por cenário que tem números válidos. O texto é montado de forma **determinística** a partir dos valores já calculados (IA-5) e das alternativas reexecutadas (IA-6):

- nenhum LLM participa;
- nada é recalculado no texto.

Simulações sem números (reconciliação falhou, população vazia) não têm explicação.

## Formato

```json
{
  "execucaoId": "exec-42",
  "assinaturaPrograma": "sha256…",
  "cenario": "Vendas 120%",
  "multiplicadorVendas": "1.2",
  "tipo": "SUGESTAO_VALIDADA",
  "resumo": "Com vendas a 120% do realizado, o custo proposto no mês é R$ 75,00 (…) Alternativa validada por reexecução do mesmo programa: reduzir taxa da regra \"p1\" de 5% para 4,58% (…)",
  "numeros": {"custoProjetado": "37.50", "orcamento": "35", "excesso": "2.50", "p1.taxa.antes": "0.05", "p1.taxa.depois": "0.0458", "…": "…"},
  "limitacoes": ["1 venda(s) do público sem regra aplicável foram calculadas pela taxa contratual (BASE_COMMISS).", "…"]
}
```

`execucaoId` vem de `contexto.execucaoId`, enviado pelo backend. Ele fica `null` quando não é informado.

| `tipo` | Quando |
|---|---|
| `SEM_ORCAMENTO` | Sem orçamento: só custo proposto, contratual e projetado |
| `DENTRO_DO_ORCAMENTO` | Custo projetado ≤ orçamento (folga e % de uso) |
| `ACIMA_DO_ORCAMENTO` | Excede, e a calibração não foi solicitada |
| `SUGESTAO_VALIDADA` | Excede, e há alternativa **verificada por reexecução**: parâmetros antes/depois, custo recalculado e folga |
| `SEM_SOLUCAO_VIAVEL` | Excede, e nem os parâmetros no mínimo cabem. Informa o custo mínimo e a parcela contratual não ajustável |
| `SUGESTAO_INDISPONIVEL` | A busca falhou ou estourou os limites. Nenhuma sugestão aparece no texto |

## Limitações citadas

- vendas no fallback contratual;
- vendas que mudam de faixa pelo multiplicador;
- vendas em conflito;
- exclusões (fora do público, sem taxa contratual, taxa ambígua), com quantidade e valor;
- a premissa da projeção linear (dias ÷ 30);
- bloqueio do encaminhamento ao gerente, só no cenário de 100%, montado a partir dos dados;
- pendências de base aceitas;
- o aviso de simulação.

## Garantia: o texto não altera números

- Cada número citado é registrado em `numeros` com o **mesmo valor** usado na formatação.
- Valores monetários aparecem como R$ sem arredondar de novo. O sinal fica no texto ("a mais"/"a menos").
- Taxas e fatores aparecem como percentual da fração guardada (0,0458 → 4,58%).
- Percentuais já calculados aparecem como estão.

`tests/test_explicacoes.py` extrai **todo** número do `resumo` e das `limitacoes` em cada tipo e confirma que ele existe em `numeros`, diretamente ou ×100 quando exibido em %. Os ids das regras entre aspas são ignorados. O teste também confere:

- que `numeros` é igual aos campos de `resultados` e `calibracoes`;
- a distinção entre sugestão validada, ausência de solução e falha;
- o vínculo com a execução e o cenário;
- o determinismo.

Com dados reais (NOV/25, 4.973 vendas, orçamento de R$ 450 mil), os 4 cenários foram explicados sem nenhum número fora de `numeros`.
