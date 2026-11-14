# IA-5 — Quatro cenários e comparação orçamentária

`POST /api/v2/simular` executa 80%, 100%, 120% e 150% sobre a população da proposta e devolve custo contratual, custo proposto, projeção no período da campanha e enquadramento frente ao orçamento. As definições são as mesmas do `SimulacaoCenariosService` do backend (BACK-8), para que o enquadramento calculado no Python coincida com o do Java.

Nada desta etapa usa LLM.

## Campos novos da requisição (todos opcionais)

| Campo | Origem | Uso |
|---|---|---|
| `orcamento` | BACK-8 (orçamento confirmado) | Teto comparado ao custo projetado de cada cenário |
| `periodoCampanha{dataInicio, dataFim}` | Vigência da campanha | Fator de projeção = dias inclusivos ÷ 30 (escala 6). Ausente: mês inteiro da competência |
| `taxasContratuais[]` | BACK-10 (`taxasContratuais`) | Custo contratual e fallback contratual. Aceita `taxa` ou `percentual` |
| `vendas[].descriCargo` | BACK-10 | Separa cargos com mesmo código e taxas diferentes (150 = GERENTE DE LOJA / GERENTE QUIOSQUE) |
| `vendas[].taxaContratual` | BACK-10 (opcional) | Taxa já resolvida pelo backend; tem precedência |
| `pendenciasAceitas[]` | BACK-7 | Devolvidas como `riscos` |

Sem `cenarios` e sem `pedido`, os cenários padrão são os quatro, sem chamar o LLM.

## Cálculo

1. **População (escopo):** vendas que pertencem ao público de ao menos uma regra (marca, loja, cargo, canal, matrícula). Faixa e vigência não definem o público. O mesmo escopo vale para os quatro cenários.
2. **Vigência das regras:** não filtra as vendas históricas da competência de referência, igual ao backend. Ela define o período da projeção.
3. **Por venda e por cenário:** valor escalado (HALF_UP, 2 casas). As faixas são reavaliadas pelo valor escalado, e a regra de maior especificidade é aplicada. Sem regra aplicável na faixa, aplica-se a **taxa contratual**, somada em `porBloco["BASE_CONTRATUAL"]`.
4. **Custo contratual:** Σ HALF_UP(valor escalado × taxa contratual) sobre o escopo.
5. **Projeção:** `custoProjetado` = HALF_UP(custo proposto × fator); `deltaProjetado` = HALF_UP(diferença × fator).
6. **Enquadramento:** `custoProjetado ≤ orcamento` → `ENQUADRADO`; acima → `ACIMA_DO_TETO`; sem orçamento → `NAO_APLICAVEL`. Os nomes são os do `EnquadramentoOrcamentoCenarioDTO`.
7. **Encaminhamento:** `orcamento.valorEncaminhamento` é o custo projetado do cenário de 100%, valor usado pelo BACK-4. Fica apto só se o cenário de 100% estiver enquadrado e não houver venda não calculável.

## Reconciliação (sem ela, nenhum número é devolvido)

- Σ `porBloco` = Σ `porMatricula` = `totalComissao`, em cada cenário (já existia).
- Vendas com regra + fallback + conflito + sem taxa = vendas do escopo, em cada cenário.
- O total de vendas do código livre bate com o do template (teste diferencial já existente).

## Exclusões (`exclusoes[]`, nunca viram zero)

| Código | Bloqueia encaminhamento | Situação |
|---|---|---|
| `FORA_DO_PUBLICO` | Não | Venda fora do público de todas as regras (fora do escopo, como no backend) |
| `SEM_TAXA_CONTRATUAL` | Sim | Venda do público sem taxa para marca + cargo |
| `TAXA_CONTRATUAL_AMBIGUA` | Sim | Mais de uma taxa possível e sem descrição de cargo para desempatar |
| `CONFLITO_REGRAS` | Sim | Regras empatadas em especificidade para a mesma venda |

Cada item traz `quantidade`, `valorVendas` e até 50 `vendaIds`.

## Compatibilidade

Sem `taxasContratuais` (contrato anterior), a simulação continua funcionando: `custoContratual` fica nulo e vendas do público sem regra ficam sem comissão. Nesse caso, uma observação avisa que o custo contratual não foi calculado.

## Diferenças conhecidas em relação ao motor Java (escopo do IA-4)

| Situação | Backend (Java) | Serviço de IA (Python) |
|---|---|---|
| Empate de especificidade, ambas com ou sem faixa | Aplica a primeira regra | Não calcula a venda e a lista como `CONFLITO_REGRAS` |
| Venda sem taxa contratual | Entra com taxa base 0 e marca impedimento | Fica fora do escopo como `SEM_TAXA_CONTRATUAL` |
| Regra com canal `PADRAO` | Sem filtro de canal | Só casa vendas sem canal ou com canal `PADRAO` |
| Matrícula da regra | Comparação sem diferenciar maiúsculas | Comparação exata |

Em todos esses casos o enquadramento pode divergir. Eles devem ser alinhados no IA-4 (equivalência por venda).

## Validação com dados reais

Simulação sobre as bases limpas do IA-9 (NOV/25 e JUL/25, ~5 mil vendas cada, 3 regras com faixa): cerca de 0,5 s por execução dos quatro cenários. A reconciliação fecha em todos os cenários.

**Pendente:** comparação centavo a centavo com o `SimulacaoCenariosService` sobre a mesma base importada no backend.

## Testes

`tests/test_cenarios_orcamento.py` usa valores calculados à mão pelas regras do backend. Cobre:

- os quatro cenários, fallback, reavaliação de faixa, projeção, enquadramento e resumo;
- as exclusões e o cargo 150;
- a compatibilidade sem taxas;
- a vigência sobre vendas históricas;
- a reconciliação;
- o contrato JSON da rota.
