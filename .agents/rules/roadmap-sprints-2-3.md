# Roadmap de Sprints — Contexto Futuro

Este documento descreve o que vem nas Sprints 2 e 3 para que o agente
não construa nada antes do tempo nem feche portas.

## Sprint 2 — Simulação, Tools e Sugestão Orçamentária

### O que muda

O serviço deixa de ser stateless de ida e volta e vira um **laço**:

1. Spring → Python: texto + tools disponíveis
2. Python envia ao LLM: texto + lista de tools
3. LLM responde: *"quero chamar `simular(regra, competencia, cenario)`"* — ele não executa, só **pede**
4. Python valida os parâmetros e faz HTTP no Spring
5. Spring calcula e devolve os números
6. Python entrega ao LLM → LLM ou pede outra tool ou escreve resposta final

> LLM = cérebro / Spring = calculadora / Python = mãos

### Cuidados a ter desde já (Sprint 1)

- **Manter `core/`, `api/routes/` e `providers/` separados.** Se colados, adicionar o laço vira reescrita; separados, vira acréscimo.
- **Não implementar nada de tool calling agora.** Apenas preservar a arquitetura em camadas.

### As quatro alavancas orçamentárias

Na Sprint 2, o LLM escolherá entre estas e apenas estas alavancas:
1. Taxa (percentual)
2. Público (marca / loja / cargo / funcionário)
3. Bônus
4. Vigência

Não existem produto, canal, equipe ou região nas bases — sugestões nesses eixos são impossíveis de calcular.

### Limites do laço

- **Teto de iterações:** máximo 5–6 chamadas de tool por requisição (evita loop infinito).
- **Timeout em cascata:** Spring espera Python, que espera Spring — os limites precisam ser coerentes.

### Explicação de cenários (Sprint 2, segunda função)

Receber os números calculados pelo Spring (80%, 100%, 120%) e redigir a comparação em português.
É geração de texto sobre números que outra pessoa calculou — tecnicamente simples.

### Pendência com o cliente (bloqueia Sprint 2)

O orçamento não tem escopo nem comportamento definidos:
- É por funcionário, campanha, loja, marca ou operação inteira?
- Estourar bloqueia ou só alerta?

Isso muda a assinatura das tools de Sprint 2. Não bloqueia Sprint 1.

---

## Sprint 3 — Anomalias e Fechamento

### Detecção de anomalias — NÃO é LLM

É estatística. Usar **IQR (intervalo interquartil)** — não desvio padrão, que é distorcido pelos próprios outliers.

Comparar a venda de um funcionário contra a distribuição dos colegas da **mesma marca e cargo na mesma competência**.
Com 30.018 registros de vendas, roda em segundos com pandas.

### Onde o LLM entra (Sprint 3)

Depois da detecção estatística. Recebe a anomalia já identificada e descreve em português:

> *"MATRIC-412 vendeu R$ 180.000 em novembro, três vezes a mediana dos vendedores da marca PRETO naquela competência. Vale conferir se há lançamento duplicado."*

Verbo: **conferir**, não "corrigir". Anomalia é indício para auditoria, não erro comprovado.

### Distinções importantes

| Conceito        | O que é                               | O que fazer         |
|-----------------|---------------------------------------|---------------------|
| Exceção         | Férias, bônus previsto                | Aplicar — é regra   |
| Inconsistência  | Matrícula ausente, duas taxas possíveis | Conciliar — exige decisão |
| Anomalia        | Venda muito fora do padrão comparável | Investigar — é indício |

### Decisão a tomar com o time (Sprint 3)

O cálculo estatístico fica no Spring ou no Python?
- Diferente do cálculo de comissão, aqui não há motor compartilhado com a apuração.
- Python com pandas é o caminho mais rápido e defensável.
- **Decidir explicitamente, não por omissão.**
