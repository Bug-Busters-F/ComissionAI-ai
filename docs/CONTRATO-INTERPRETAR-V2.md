# Contrato v2 — interpretação, agente e simulação

Documento para o time do Spring. Fonte da verdade: `src/app/schemas/proposta.py` e o Swagger do serviço
(`/docs`). O v1 (`POST /api/v1/interpretar`) continua funcionando e convive com o v2 nesta sprint.

## O que a IA faz e não faz
- **Propõe**; a aprovação é do usuário. Nunca devolve `status`/ativação de regra, versão publicada, `id` persistido
  nem identificadores financeiros (valor de comissão, protocolo de cálculo).
- **Não acessa o banco.** O que precisa saber, consulta no Spring (`/api/v1/consultas-ia/...`, `BACKEND_BASE_URL`).
- Quando não há evidência, devolve **pendência objetiva** (nunca valor inventado).

## Rotas

| Rota | Função | Situação |
|---|---|---|
| `POST /api/v2/interpretar` | Pedido em linguagem natural → lista de propostas (agente com ferramentas) | Implementada (IA-1/2/3/4) |
| `POST /api/v2/simular` | Propostas → simulação em sandbox (template ou código livre) | Implementada (requisito do cliente) |
| `POST /api/v2/reinterpretar` | Texto alterado de uma regra → proposta(s) de substituição | Implementada (IA-6) |
| `POST /api/v2/atualizar-artefatos` | Campos editados → explicação/código atualizados | Implementada (IA-6/IA-7) |

Erros: mesmo formato do v1 (`{"detail", "error_code"}`): `401 LLM_AUTH_ERROR`, `429 LLM_RATE_LIMIT_ERROR`,
`502 LLM_PROVIDER_ERROR`, `504 LLM_TIMEOUT_ERROR`, `422` (validação).

## `POST /api/v2/interpretar`

```json
{
  "texto": "3% para vendedores da loja 75 e 2% para gerentes em dezembro",
  "contexto": {"campanhaId": "12", "revisao": 3, "origem": "NOVA", "substituiVersao": null},
  "vigenciaCampanha": {"inicio": "2026-12-01", "fim": "2026-12-31"},
  "dataReferencia": "2026-09-07",
  "competencia": "2026-12",
  "catalogo": {"marcas": {"10": "PRETO"}, "cargos": {"100": "VENDEDOR LOJA"}, "canais": ["ECOMMERCE"], "lojas": {"75": "Loja 75"}}
}
```

- `contexto`: ids **opacos**, devolvidos em eco. `campanhaId`/`substituiVersao` precisam ser **numéricos** se forem usados
  na consulta de concorrência (o Spring valida). Em `origem="VERSAO_EXISTENTE"` a versão anterior é ignorada na
  consulta de regras concorrentes.
- `vigenciaCampanha`: vigência comum. **Todas as regras a herdam**; período diferente citado no texto gera
  `VIGENCIA_INCOMPATIVEL` e a vigência da campanha é mantida.
- `catalogo`: opcional. Sem ele (ou para o que ele não cobre) o agente resolve nomes por ferramenta.
- `competencia` (`YYYY-MM`): usada nas consultas de base; se ausente, vem do `dataInicio` de cada proposta.

Resposta:

```json
{
  "contexto": {"campanhaId": "12", "revisao": 3, "origem": "NOVA", "substituiVersao": null},
  "status": "PROPOSTA_COM_PENDENCIAS",
  "propostas": [{
    "idLocal": "p1",
    "condicoes": {"codCargo": 100, "descriCargo": "VENDEDOR LOJA", "codLoja": 75, "matricula": null, "faixaValor": null},
    "operacao": {"tipo": "TAXA_ABSOLUTA", "valor": "0.0300"},
    "taxa": "0.0300",
    "bonus": null,
    "dataInicio": "2026-12-01", "dataFim": "2026-12-31",
    "origem": {"trecho": "3% para vendedores da loja 75", "inicio": 0, "fim": 29},
    "referencias": [], "evidencias": [],
    "explicacao": null, "codigoPython": null,
    "confianca": "1.00",
    "pendencias": []
  }],
  "pendenciasGerais": [],
  "trechosNaoMapeados": [],
  "trilhaFerramentas": []
}
```

| Campo | Observação |
|---|---|
| `propostas[]` | Uma por regra. `idLocal` (`p1`, `p2`…) só correlaciona dentro da resposta; **não é id de negócio**. |
| `condicoes.faixaValor` | `{min, max, minInclusivo, maxInclusivo}` sobre o valor **de cada venda**. Padrão `[min, max)`. |
| `condicoes.matricula` | String (ex.: `MATRIC-56`). |
| `operacao` / `taxa` | `operacao` guarda o que o gestor pediu: `TAXA_ABSOLUTA` (valor = taxa) ou ajuste sobre a base (`ADICIONAR_PP`/`REDUZIR_PP`/`AUMENTAR_PERCENTUAL`/`REDUZIR_PERCENTUAL`, valor = delta em escala decimal: 1 p.p. ou 1% = `0.0100`). Nos ajustes, `taxa` é a **taxa final** calculada sobre a base consultada (escala 4, `HALF_UP`; ex.: base 2,5% +1 p.p. = `0.0350`; +1% relativo = `0.0253`) e a base fica em `referencias` (`BASE_COMISS`, `taxaBase`). Sem base única: `taxa=null` + pendência (`BASE_AUSENTE`, `AMBIGUIDADE_PUBLICO` quando o público abrange várias bases, `TOOL_FALHA`). Expressão ambígua (ex.: "mais 1%": pontos ou relativo?) volta com `operacao=null`, `taxa=null` e `TAXA_INVALIDA` com `pergunta`. |
| `bonus` | `{percentual, valorFixo}`: adicional **sobre a venda** (valor fixo **por venda**). |
| `origem` | Trecho **literal** do pedido (validado contra o texto). |
| `referencias` | De onde veio cada dado consultado (cadastro, base, regra). |
| `evidencias` / `trilhaFerramentas` | Ferramentas usadas, argumentos, status (`OK`/`SEM_DADOS`/`AMBIGUO`/`FALHA`), resumo e duração. |
| `explicacao` / `codigoPython` | Gerados dos campos finais de cada proposta (IA-7). A explicação cita o trecho, a base e a operação, os cadastros, a vigência (herdada ou não) e as edições manuais. O Python é o motor do template de simulação com a regra embutida: `simular(vendas, regras, cenario)` recebe as **demais** regras da proposta; equivalência validada contra os casos de ouro. `codigoPython=null` se o código não passar na análise estática. |
| `confianca` | Determinística (não é o LLM). Não persistir. |
| `trechosNaoMapeados` | Partes do pedido que não viraram regra. Nada é descartado em silêncio. |
| `status` | `PROPOSTA_COMPLETA`, `PROPOSTA_COM_PENDENCIAS` ou `SEM_PROPOSTA`. |

### Catálogo de pendências
`CAMPO_AUSENTE`, `AMBIGUIDADE_CARGO`, `AMBIGUIDADE_PUBLICO`, `CADASTRO_INEXISTENTE`, `MATRICULA_INVALIDA`,
`CRITERIO_NAO_SUPORTADO`, `TRECHO_INCOMPLETO`, `VIGENCIA_INCOMPATIVEL`, `BASE_AUSENTE`, `CONFLITO_REGRA`,
`TOOL_FALHA`, `LIMITE_AGENTE_ATINGIDO`, `TAXA_INVALIDA`, `SIMULACAO_NAO_VALIDADA`, `NAO_SUPORTADO_NA_APURACAO`.
Cada pendência: `{codigo, mensagem, campo, pergunta}`. Códigos são estáveis: tratem pelo `codigo`, não pelo texto.

### Consultas e limites do agente (por requisição)

Por padrão, `AGENT_USE_LLM_DECISIONS=false`: o LLM faz a extração bruta inicial. O Python agenda as
consultas conhecidas na ordem cadastro → matrícula → base → concorrência, conforme as dependências
resolvidas. Ferramentas e argumentos continuam sendo validados e todas as evidências são devolvidas.
Consultas idênticas reaproveitam o cache da requisição, incluindo a evidência em cada bloco afetado.
Reaproveitar um resultado não consome outro passo nem outra consulta do orçamento.

`AGENT_MAX_STEPS=6`, `AGENT_MAX_TOOL_CALLS=8`, `AGENT_MAX_DURATION_SECONDS=45`. A extração consome um passo;
cada nova consulta consome outro. O tempo continua sendo verificado entre consultas, inclusive antes de
usar o cache. Ao atingir um limite, os blocos são preservados e as consultas não feitas recebem
`LIMITE_AGENTE_ATINGIDO`. O timeout de cada ferramenta continua em `TOOL_TIMEOUT_SECONDS`.

O modo anterior pode ser habilitado com `AGENT_USE_LLM_DECISIONS=true`; nesse modo há chamadas adicionais
ao modelo para decisões e permanecem as proteções contra paradas antecipadas. Falha do LLM após a extração
mantém o apurado com `TOOL_FALHA`; erro de autenticação propaga. O modo padrão elimina essas chamadas
adicionais para consultas já determinadas pelo código.

Para Groq, `LLM_RATE_LIMIT_MAX_RETRIES=1` permite uma retentativa de 429 somente se houver `Retry-After`
válido, com espera no máximo `LLM_RATE_LIMIT_MAX_WAIT_SECONDS=5`, e se ela couber no tempo restante de
`LLM_TIMEOUT_SECONDS`. A segunda tentativa e o fallback IPv4 usam o timeout restante, sem reiniciar o
orçamento. Sem prazo, com prazo longo, ou após esgotar as tentativas, o erro propaga como
`429 LLM_RATE_LIMIT_ERROR`. Quando disponível, o serviço devolve `Retry-After` no cabeçalho da resposta,
arredondado para cima em segundos. O corpo de erro mantém `{detail, error_code}`. Autenticação e
permissão não são retentadas. Isso não amplia a cota da organização na Groq.

O `AI_READ_TIMEOUT` do Spring continua configurado em 60s; não é necessário mudar o contrato de proposta
nem o formulário para usar o modo padrão. Caso o Spring precise apresentar a espera ao navegador, ele
precisa preservar o status/cabeçalho recebido da IA (não implementado por esta alteração).

## `POST /api/v2/reinterpretar` (IA-6)
Entrada: `idLocal`, `textoAlterado`, `blocoAtual`, `demaisBlocos`, `vigenciaCampanha`, `contexto`, `catalogo`.
- Só o bloco `idLocal` é reinterpretado; `demaisBlocos` são apenas lidos (conflitos) e **não** voltam na resposta.
- O que o texto novo não cita é herdado do `blocoAtual` (público, faixa, taxa/operação/bônus); o que ele cita é
  reinterpretado. O frontend confirma antes de substituir valores editados manualmente.
- `propostasSubstituicao`: 1 bloco mantém o `idLocal`; divisão em vários gera `p1`, `p1_2`, `p1_3`…
- `camposAlterados`: caminhos alterados em relação ao `blocoAtual` (ex.: `taxa`, `operacao`, `condicoes.codLoja`).
- `CONFLITO_REGRA` só para público, faixa e período sobrepostos **com a mesma especificidade** (o motor não teria
  regra vencedora), comparando com `demaisBlocos` e entre os blocos da própria divisão.
- `contexto.origem=VERSAO_EXISTENTE`: a consulta de concorrência ignora a própria campanha (`ignorarCampanhaId`).

## `POST /api/v2/atualizar-artefatos` (IA-6/IA-7)
Entrada: `bloco` (campos atuais), `camposEditados`, `origemCampos` (`MANUAL`/`IA`), `contexto`.
- Determinístico: não chama o LLM nem reinterpreta texto; nenhum campo é alterado por inferência.
- Campos em `camposEditados` contam como `MANUAL`, salvo indicação diferente em `origemCampos`.
- Taxa `MANUAL`: `operacao` vira `TAXA_ABSOLUTA` com o novo valor, a referência `BASE_COMISS` sai e as pendências de
  `taxa` são substituídas; a explicação informa "definida manualmente pelo gestor (origem: MANUAL)".

## `POST /api/v2/simular`
```json
{
  "propostas": [ /* BlocoProposta do interpretar, com taxa e/ou bonus */ ],
  "competencia": "2026-12",
  "pedido": "e se as vendas crescerem 20%?",
  "cenarios": [],
  "filtro": {"loja": 75}
}
```
- Sem `cenarios` e sem `pedido`: usa 80%, 100% e 120% das vendas. Com `pedido`, o agente monta os cenários.
- **Sempre simulação**: `simulacao="SIMULACAO_SANDBOX"` e um `aviso`; nunca substitui a apuração.
- `origem="TEMPLATE"` (casos genéricos: público, taxa, faixa, bônus, cenários) ou `"CODIGO_LIVRE"` (cálculo extra
  pedido, ex.: ranking). Código livre devolve `codigoExecutado` e as premissas em `observacoes`.
- **Sem validação, sem números:** se o sandbox bloquear/falhar ou o resultado não passar nas checagens, `resultados`
  vem vazio com `SIMULACAO_NAO_VALIDADA` (ou `TOOL_FALHA`).
- Regras de cálculo espelham a apuração: uma regra por venda (maior especificidade; faixa desempata; empate = venda em
  conflito, não calculada), `comissão = valor×taxa + valor×bônus% + bônus fixo`, cada parcela `HALF_UP` escala 2.
  Garantido pelos **casos de ouro** compartilhados (`tests/golden/golden_cases.json`).
- Vendas sem proposta aplicável ficam fora (a base de comissão não entra na simulação de propostas).

## Consultas ao backend (usadas pelas tools)
`GET /api/v1/consultas-ia/{marcas|lojas|cargos}`, `/matriculas/{m}`, `/bases`, `POST /regras-concorrentes`,
`GET /dados-simulacao`. Formato de resposta fixado com o backend (`encontrado` + `itens` etc.). Distinção usada pela IA:
`encontrado=false`/lista vazia = **SEM_DADOS**; timeout, 5xx e JSON inválido = **FALHA** (1 retry só para falha transitória).
