# Fluxo do dado na trilha de IA — Dom Rock

Como o dado caminha pelo sistema em cada sprint, com ênfase no serviço Python.

---

## Regras que valem nas três sprints

Três coisas não mudam do começo ao fim. Se em algum momento uma delas for violada, é sinal de que a arquitetura torceu.

**O front nunca fala com o serviço de IA.** O Vue só conhece o Spring. O Spring é quem chama o Python. Se o front chamasse os dois, existiriam duas fontes de validação e ninguém saberia qual manda.

**O serviço Python não acessa o banco de negócio.** Tudo que ele precisa saber sobre a empresa chega na requisição. Isso o mantém stateless — você pode reescrevê-lo inteiro numa tarde sem afetar ninguém, e testá-lo é trivial.

**O LLM nunca é a fonte da verdade.** Ele preenche formulário e escolhe caminhos; quem decide o que é válido é a validação determinística, e quem calcula dinheiro é o Spring.

---

# Sprint 1 — Interpretação

O gestor descreve uma regra em linguagem natural e o sistema devolve um formulário preenchido para ele revisar.

Nesta sprint o serviço Python é **stateless e sem tools**: entra texto, sai JSON. Uma chamada ao LLM, sem laço.

Exemplo que vamos seguir: *"3% para os vendedores da loja 75 em dezembro"*.

## Fora do serviço de IA

### Vue → Spring

O front manda o mínimo. Ele nem sabe que existe IA no meio.

```json
{ "texto": "3% para os vendedores da loja 75 em dezembro" }
```

### Spring → Python

Aqui o Spring engorda a requisição. Ele consulta o banco e anexa tudo que existe de verdade:

```json
{
  "texto": "3% para os vendedores da loja 75 em dezembro",
  "data_referencia": "2026-09-07",
  "catalogo": {
    "marcas": [{"codigo": 10, "nome": "PRETO"}, {"codigo": 20, "nome": "BRANCO"}],
    "lojas": [{"codigo": 75, "nome": "...", "marca_codigo": 20}],
    "cargos": [{"codigo": 100, "descricao": "vendedor de loja"}]
  }
}
```

Dois campos são requisitos seus, não do Spring:

- **`catalogo`** — só o Spring acessa o banco de negócio, então você recebe tudo pronto. As 6 marcas, 80 lojas e 4 cargos cabem tranquilamente no contexto do modelo.
- **`data_referencia`** — sem ela, "em dezembro" é indecidível. Dezembro de 2026 ou de 2025?

## Dentro do serviço Python — cinco etapas

### 1. Montagem do prompt

Você constrói uma instrução juntando quatro coisas:

1. O texto do gestor
2. O catálogo formatado como lista de valores permitidos
3. Cinco a oito exemplos resolvidos, incluindo dois que terminam em pendência
4. A regra de ouro — *na dúvida, devolva pendência; nunca invente parâmetro*

O catálogo no prompt é o que impede o modelo de inventar uma marca "ROXO". Ele só pode escolher entre o que você listou.

> Você não "melhora o prompt". Você **monta** o prompt. O texto do gestor é um dos ingredientes, não o prompt em si.

### 2. Chamada ao LLM com saída estruturada

Você não pede "responda em JSON" e torce. Você passa o JSON Schema gerado pelo Pydantic (`RegraInterpretada.model_json_schema()`) como `response_schema`, e o provedor obriga o modelo a respeitar o formato.

O modelo devolve algo assim:

```json
{
  "status": "ok",
  "operacao": "SUBSTITUIR_PERCENTUAL",
  "percentual": "3%",
  "publico": {"loja_codigo": 75, "cargo_codigo": 100},
  "inicio": "dezembro",
  "fim": null
}
```

Repare que ainda está sujo: `"3%"` é string, `"dezembro"` não é data. **É de propósito.** Normalização é trabalho determinístico, e código faz isso melhor e mais barato que LLM.

### 3. Validação estrutural

O Pydantic checa: os campos existem? Os tipos batem? `operacao` é um valor válido do Enum? Se algo estiver fora, levanta `ValidationError` dizendo exatamente qual campo e por quê.

Etapa praticamente de graça — você só declarou a classe.

### 4. Normalização

- `"3%"` → `Decimal("0.0300")`
- `"dezembro"` + `data_referencia: 2026-09-07` → `2026-12-01` a `2026-12-31`
- `fim: null` continua `null` **de propósito** — é informação (o gestor não especificou fim), e quem aplica o default de 30 dias é o Spring

### 5. Validação semântica

A etapa que dá valor ao serviço. Aqui você confronta o resultado com a realidade:

| Pergunta | Neste exemplo |
|---|---|
| A loja 75 existe no catálogo? | Sim |
| Se o texto citasse marca, ela bateria com a loja? | "loja 75 da marca PRETO" seria pendência — a 75 é BRANCO |
| O percentual é plausível? | 3% está na faixa; 300% viraria pendência |

E a validação que depende de dois campos ao mesmo tempo: se a operação fosse `ACRESCENTAR_PONTO_PERCENTUAL` e o cargo fosse 150, viraria pendência — gerente de loja e gerente de quiosque compartilham o código 150 com taxas base diferentes, então não dá para saber sobre qual somar.

Em Pydantic isso é `@model_validator(mode="after")`, não um `field_validator` isolado.

## A volta

### Python → Spring

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

Se a validação tivesse falhado, `status` seria `"pendencias"` e o array traria o quê, o porquê e a pergunta a fazer ao usuário.

### Spring → Vue

**O Spring valida tudo de novo.** Não é desperdício — é proposital. Ele resolve os códigos contra o banco e não confia num serviço externo para gravar dados. Depois salva como **rascunho**, nunca ativo.

O front preenche o formulário com esses campos, o gestor revisa, corrige o que quiser e salva.

## O que define a Sprint 1

A resposta tem sempre dois destinos possíveis: **regra ou pendência**. Nunca "chutei um valor razoável". Quando o sistema não sabe, ele pergunta — e é assim que o conhecimento tácito que hoje se perde na cabeça dos gestores vira dado registrado.

---

# Sprint 2 — Simulação, tools e sugestão orçamentária

Aqui o fluxo muda de forma. Deixa de ser uma ida e volta e vira um **laço**.

## O cálculo fica no Spring. Sempre.

A simulação usa dados reais da empresa, e o cálculo tem que rodar no Spring — não por organização, mas porque **o módulo de cálculo é reutilizado pela simulação e pela apuração**. As entradas mudam (dados históricos vs. dados reais da competência), mas a matemática de aplicar uma regra é a mesma.

Se você reimplementar o cálculo em Python para simular, vão existir dois motores. Um dia divergem, e a simulação promete um número que a apuração não entrega. Numa banca, é a pergunta que derruba a apresentação.

## Quem executa a tool

O serviço Python não "só chama" a tool — ele **executa o laço**:

1. Você manda ao LLM o texto + a lista de tools disponíveis
2. O LLM responde: *"quero chamar `simular(regra, competencia_referencia, cenario)`"* — ele não executa nada, só **pede**
3. **Você** recebe o pedido, valida os parâmetros e faz um HTTP no Spring
4. O Spring calcula e devolve os números
5. Você entrega o resultado de volta ao LLM
6. O LLM ou pede outra tool, ou escreve a resposta final

> O LLM é o cérebro, o Spring é a calculadora, e o serviço Python são as mãos.

### Consequências práticas

Isso cria uma chamada **Spring → Python → Spring**. Funciona bem em HTTP, mas exige dois cuidados:

- **Timeout em cascata** — o Spring está esperando você, que está esperando o Spring. Os limites precisam ser coerentes entre si.
- **Teto de iterações** — defina um máximo de 5 ou 6 chamadas de tool por requisição, para o LLM não ficar chamando tool para sempre.

## Sugestão orçamentária: a divisão que funciona

O erro tentador é deixar o LLM chamar `simular()` vinte vezes até achar um número que caiba no orçamento. Três problemas: cada iteração custa segundos e tokens, o resultado **não é reprodutível** (rodar duas vezes pode dar 2,6% e 2,7%), e pode simplesmente não convergir.

A divisão certa tem três papéis:

| Quem | Faz o quê |
|---|---|
| **LLM** | Escolhe qual alavanca puxar |
| **Spring** | Calcula o número da alavanca, deterministicamente |
| **LLM** | Recebe os resultados e redige a justificativa |

**O LLM escolhe a alavanca.** Reduzir a taxa? Cortar o bônus fixo? Estreitar o público (tirar os gerentes da campanha)? Encurtar a vigência? São escolhas de negócio qualitativamente diferentes, e é aí que o modelo é bom.

**O Spring calcula.** Uma tool tipo `buscar_ajuste(alavanca, orcamento_alvo)` que faz bisseção sobre a taxa até caber. Converge em ~10 iterações, em milissegundos, sempre no mesmo valor.

**O LLM redige.** *"Reduzir para 2,6% mantém o bônus da Ana e cabe no cenário de 120% com R$ 44 de folga; alternativamente, cortar o bônus de R$ 500 permite manter os 3%, mas remove o reconhecimento individual que você tinha proposto."*

Isso é auditável. Quando alguém perguntar "por que 2,6%?", a resposta é *"bisseção sobre a taxa com orçamento de R$ 4.000 no cenário de 120%"*, não *"o modelo sugeriu"*.

## As alavancas são só quatro

"Onde cortar gastos" pressupõe dimensões para cortar. Nas bases reais existem apenas:

1. **Taxa**
2. **Público** (marca / loja / cargo / funcionário)
3. **Bônus**
4. **Vigência**

Não há produto, canal, equipe nem região. Uma sugestão do tipo "corte o incentivo do e-commerce" é impossível de calcular porque o dado não existe.

Isso na verdade facilita: a lista é fechada e pequena, então você enumera as quatro e pede ao LLM que escolha entre elas, em vez de deixá-lo inventar.

## Pendência com o cliente que bloqueia esta sprint

**O orçamento não tem escopo nem comportamento definidos.** É por funcionário, campanha, loja, marca ou operação inteira? Estourar bloqueia ou só alerta?

Isso muda a assinatura das suas tools — `buscar_ajuste` precisa saber contra o que comparar. E há um detalhe fino: se o orçamento é da loja inteira mas a campanha atinge só os vendedores, a simulação precisa somar o custo dos gerentes que ficaram de fora.

Não bloqueia a Sprint 1, mas bloqueia esta.

## Explicação dos cenários

A segunda função de IA da sprint, e a mais simples: receber os números já calculados pelo Spring (80%, 100%, 120%) e redigir a comparação em português.

> *"A proposta custa R$ 900 a mais que o cenário vigente; cabe no orçamento a 100% com R$ 300 de folga, mas ultrapassa em R$ 340 se as vendas crescerem 20%."*

É geração de texto sobre números que outra pessoa calculou. Tecnicamente trivial, e é o requisito de explicabilidade do desafio.

---

# Sprint 3 — Anomalias e fechamento

## Detecção de anomalias não é LLM

É estatística. O critério de três desvios padrão que está no backlog pressupõe histórico diário, que as bases não oferecem de forma uniforme.

Comece com o que os dados suportam: comparar a venda de um funcionário contra a distribuição dos colegas da **mesma marca e cargo na mesma competência**.

Use **IQR (intervalo interquartil)** em vez de desvio padrão. Motivo: o desvio padrão é ele próprio distorcido pelos outliers, e outlier é exatamente o que você está procurando. Com 30.018 registros de vendas, isso roda em segundos com pandas.

## Onde o LLM entra

Depois. Ele recebe a anomalia já detectada e a descreve em português:

> *"MATRIC-412 vendeu R$ 180.000 em novembro, três vezes a mediana dos vendedores da marca PRETO naquela competência. Vale conferir se há lançamento duplicado."*

Note o verbo: **conferir**, não "corrigir". Anomalia é indício para auditoria, não erro comprovado. A distinção importa:

| Conceito | O que é | O que fazer |
|---|---|---|
| **Exceção** | Férias, bônus previsto | Aplicar — é regra |
| **Inconsistência** | Matrícula ausente, duas taxas possíveis | Conciliar — exige decisão |
| **Anomalia** | Venda muito fora do padrão comparável | Investigar — é indício |

## O fluxo desta sprint

O caminho é o mesmo da Sprint 2, com uma tool nova:

1. Spring → Python: pedido de análise da competência
2. Python chama a tool `detectar_anomalias(competencia)` no Spring — ou roda o cálculo estatístico localmente com pandas, se o time preferir manter estatística fora do Java
3. Recebe a lista de registros suspeitos com os números que os tornam suspeitos
4. LLM redige a descrição de cada um
5. Volta ao Spring, que apresenta para auditoria humana

**Decisão a tomar com o time:** o cálculo estatístico fica no Spring ou no Python? Diferente do cálculo de comissão, aqui não há motor compartilhado com a apuração — é análise, não dinheiro. Python com pandas é o caminho mais rápido, e é defensável. Mas decidam explicitamente, não por omissão.

---

# O que fazer agora para não fechar portas

Tool calling é Sprint 2. Na Sprint 1 seu serviço é stateless, sem tools, sem laço. Você não deve construir nada disso agora.

O que você **deve** fazer é manter três camadas separadas desde o primeiro dia:

1. **Montagem do prompt** — separada de
2. **Chamada ao LLM** — separada de
3. **Rota do FastAPI**

Se essas três estiverem coladas num arquivo só, adicionar o laço de tools na Sprint 2 vira reescrita. Separadas, vira acréscimo.
