# IA-6 — Calibração verificável por cenário excedido

Com `"calibrar": true` e `orcamento` em `POST /api/v2/simular`, cada cenário cujo custo projetado passa do orçamento recebe **uma alternativa independente** de parâmetros. A alternativa é sempre verificada por reexecução do mesmo programa da simulação (template ou código aprovado, mesma `assinaturaPrograma`).

Nada desta etapa usa LLM.

## O que é ajustado

| Ajustado | Não ajustado |
|---|---|
| `taxa` (4 casas, HALF_UP) | Público (marca, loja, cargo, matrícula, canal) |
| `bonus.percentual` (4 casas) | Faixas de valor |
| `bonus.valorFixo` (2 casas) | Vigência |
| | **Orçamento** (nunca muda) |
| | Taxa contratual das vendas sem regra (não pertence à proposta) |

Todos os parâmetros elegíveis são multiplicados pelo mesmo fator `fatorAjuste` λ ∈ (0, 1]. Assim, a proporção entre as regras que o gestor definiu é preservada.

## Algoritmo

1. **Cenário dentro do orçamento:** `NAO_NECESSARIA`, sem reexecução.
2. **Piso:** reexecuta com todos os parâmetros no mínimo representável (taxa 0,0001; bônus fixo R$ 0,01). Se nem assim cabe, o resultado é `SEM_SOLUCAO_VIAVEL`, com `custoProjetadoMinimo` e o motivo (por exemplo, a parcela contratual sozinha passa do teto).
3. **Bisseção em λ:** cada passo reexecuta o programa e guarda o **maior λ cujo custo recalculado cabe**, ou seja, a alternativa mais próxima da proposta original. O custo nunca sobe quando λ cai, porque as faixas dependem do valor da venda e não da taxa; por isso a busca converge.
4. **Resultado:** `ENQUADRADA` com `custoProjetadoRecalculado`, `folga` e `alteracoes[{idLocal, campo, antes, depois}]`, prontas para o usuário aplicar ao rascunho. Aplicar uma alternativa exige nova revisão e nova simulação (FRONT-8).

## Limites e falhas

| Configuração | Padrão | Escopo |
|---|---|---|
| `CALIB_MAX_TENTATIVAS` | 12 | Reexecuções por cenário, incluindo o piso |
| `CALIB_MAX_SEGUNDOS` | 20 | Tempo **total** da calibração na requisição, para caber no `AI_READ_TIMEOUT` do backend (60 s) |

Se uma reexecução falha, ou se os limites acabam antes de existir uma alternativa verificada, o cenário fica com `FALHA`, `motivo` preenchido e **nenhuma alteração**. Nesse caso, `statusSugestoes = "FALHA"`.

Sem orçamento, a calibração não roda: `statusSugestoes = "FALHA"` e uma pendência no campo `orcamento`.

| `statusSugestoes` | Significado |
|---|---|
| `NAO_SOLICITADA` | `calibrar` ausente ou falso |
| `OK` | Todos os cenários processados (`ENQUADRADA`, `SEM_SOLUCAO_VIAVEL` ou `NAO_NECESSARIA`) |
| `FALHA` | Ao menos um cenário não pôde ser calibrado; nada foi inventado para ele |

## Validação com dados reais

NOV/25 limpo (3.881 vendas no escopo, 3 regras, orçamento de R$ 450 mil):

- 100%, 120% e 150% receberam alternativas `ENQUADRADA`, com folga entre R$ 735 e R$ 900;
- 12 reexecuções por cenário, 8,7 s no total no Windows (subprocesso ~0,24 s por execução).

## Testes

`tests/test_calibracao.py` cobre:

- **a prova de verificabilidade:** aplicar as `alteracoes` e simular de novo reproduz exatamente o `custoProjetadoRecalculado`;
- a independência entre cenários e a proximidade do limite;
- os ajustes de bônus;
- os casos sem solução;
- as falhas de reexecução;
- os limites de tempo (compartilhado entre cenários) e de tentativas;
- o determinismo e a preservação do orçamento.
