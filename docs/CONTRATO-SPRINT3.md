# Contrato do serviço de IA — Sprint 3 (IA-5 a IA-10)

Integração backend (Spring) → IA (FastAPI) para geração e execução do programa de simulação, calibração e anomalias (BACK-9 a BACK-12, FRONT-6 e FRONT-8).

**O frontend nunca chama a IA diretamente.**

| Artefato | Onde |
|---|---|
| JSON Schema de cada request/response | `docs/contratos/*.schema.json`, gerados por `scripts/exportar_contratos.py`. O teste falha se ficarem desatualizados |
| Coleção Postman | `postman/IA5-IA10-sprint3.postman_collection.json` |
| Detalhes por tarefa | `docs/IA-5-CENARIOS-ORCAMENTO.md`, `IA-6-CALIBRACAO.md`, `IA-7-EXPLICACOES.md`, `IA-8-ANOMALIAS.md`, `IA-9-BASES-LIMPAS.md` |
| Testes de contrato | `tests/test_contrato_sprint3.py` (payload no formato exato dos DTOs Java do BACK-10) |

## 1. Cabeçalhos

| Cabeçalho | Sentido | Regra |
|---|---|---|
| `X-Internal-Api-Key` (nome em `AI_SERVICE_AUTH_HEADER`) | backend → IA | **Obrigatório em todas as rotas**, exceto `/health`, `/docs`, `/redoc` e `/openapi.json`. É a **mesma** `AI_SERVICE_API_KEY` que o backend já envia no `AiServiceClient` e que a IA usa para consultar o backend. A comparação é em tempo constante e o valor nunca é logado |
| `X-Correlation-Id` | ida e volta | Opcional na ida (`[A-Za-z0-9._:-]{1,128}`); ausente ou inválido, a IA gera um. Sempre devolvido na resposta e presente em toda linha de log da requisição (`[id]`). O `AiServiceClient` envia um UUID em **todas** as chamadas (ou o `correlationId` do MDC, se existir) e registra `Chamada ao serviço de IA <rota> com X-Correlation-Id=<id>` |

A IA **não autentica usuários** e não tem cadastro próprio. Ela confia apenas no backend, pela chave interna, e registra o `usuarioSolicitanteId` que o backend repassa.

**Sem `AI_SERVICE_API_KEY`:**

- em desenvolvimento, as rotas ficam abertas e o log avisa na subida;
- em produção, use `AI_INBOUND_AUTH_OBRIGATORIA=true`: as rotas respondem 503 `AUTH_NAO_CONFIGURADA` até a chave existir.

## 2. Identificadores (`contexto`)

Aceito em `/gerar-programa`, `/simular` e `/anomalias/analisar`, e devolvido em `contexto` na resposta (o `/executar-programa` usa o `contexto` que o backend já envia, ver §3):

```json
{"campanhaId": "42", "revisao": 3, "execucaoId": "exec-9f1", "usuarioSolicitanteId": "user-7", "versaoPrograma": "prog-v2"}
```

| Identificador | Para que serve |
|---|---|
| `campanhaId`, `revisao` | Campanha e revisão da proposta |
| `execucaoId` | Execução no backend (BACK-11). Volta em cada `explicacoes[]` e na resposta de anomalias |
| `usuarioSolicitanteId` | Só registro (log e eco) |
| `versaoPrograma` | Versão aprovada no backend (BACK-9). A IA devolve também `assinaturaPrograma` (sha256 do código executado) e a repete em cada `calibracoes[]` e `explicacoes[]` |

**Dados exatos usados:** envie em `/simular` o objeto `versoesFontes` do recorte (BACK-10). A resposta traz `versaoFontes.recorte` com:

- `hashRecorte`, `hashVendas`, `hashRh`, `hashTaxasContratuais`, `hashRegras`, `hashPendenciasAceitas` (os não nulos);
- `campanha.versaoId`, `campanha.versaoNumero`, `campanha.hashArtefatosCodigo`.

Em `/anomalias/analisar`, `versoesFontes` volta como `versaoFontes`. A IA ainda calcula o seu próprio `versaoDados`.

## 3. Rotas

### `POST /api/v2/gerar-programa` (IA-2, BACK-9)

Gera e valida o programa **antes** da revisão técnica. Devolve `origem` (`TEMPLATE` | `CODIGO_LIVRE`), `codigo`, `assinatura`, `premissas`, `pendencias` e `contexto`.

### `POST /api/v2/simular` (IA-3 a IA-7, BACK-11)

**Entrada:** o recorte do BACK-10 passa quase direto. Campos extras dos DTOs são ignorados.

| Campo | Origem no recorte | Observação |
|---|---|---|
| `competencia` | `periodo.competenciaReferencia` | `YYYY-MM` |
| `propostas[]` | Regras da proposta em revisão | `idLocal`, `taxa`, `bonus`, `condicoes` |
| `vendas[]` | `vendas` (`VendaRecorteIaDTO`) | **Fonte única** quando informada |
| `taxasContratuais[]` | `taxasContratuais` | Aceita `taxa` ou `percentual` |
| `pendenciasAceitas[]` | `pendenciasAceitas` | Viram `riscos[]` e limitações nas explicações |
| `versoesFontes` | `versoesFontes` | Ver §2 |
| `orcamento` | `campanha.orcamento` | > 0 |
| `periodoCampanha` | `{dataInicio, dataFim}` da campanha | Fator de projeção = dias inclusivos ÷ 30 |
| `cenarios[]` | Opcional | Padrão: Vendas 80/100/120/150% |
| `calibrar` | `true` para sugestões (IA-6) | Exige `orcamento` |
| `codigoAprovado` + `assinaturaPrograma` | Saída do `/gerar-programa` | Executa sem regerar (recomendado, ver §5) |

**Saída:**

| Campo | Conteúdo |
|---|---|
| `resultados[]` | Por cenário: totais, custo contratual, diferença, `custoProjetado`, contadores e `enquadramento` (mesmos nomes de `EnquadramentoOrcamentoCenarioDTO`) |
| `orcamento` | Resumo (mesmos nomes de `ResumoEnquadramentoOrcamentoDTO`), incluindo `valorEncaminhamento` e `aptoEncaminhamentoGerente` |
| `exclusoes[]` | Vendas fora do cálculo, sempre explícitas |
| `riscos[]` | Ressalvas que acompanham os números |
| `calibracoes[]` e `statusSugestoes` | Alternativas do IA-6 |
| `explicacoes[]` | Uma por cenário (IA-7): `{execucaoId, assinaturaPrograma, cenario, tipo, resumo, numeros{}, limitacoes[]}` |
| `assinaturaPrograma`, `versaoFontes`, `pendencias[]`, `contexto` | Rastreabilidade e pendências |

### `POST /api/v2/anomalias/analisar` (IA-8, BACK-12 com Ygor, FRONT-6)

- **Entrada:** `competencia`, `vendas[]` (formato `VendaRecorteIaDTO`), `dadosRh[]` (formato `ColaboradorRhRecorteIaDTO`), `parametros{k, amostraMinima}` opcionais, `versoesFontes` e `contexto`.
- **Saída:**
  - `tipo = INDICIO_PARA_CONFERENCIA`, `granularidade = DIARIA`, `metodo` e `versaoDados`;
  - `alertas[]` com valor observado, faixa esperada, grupo, amostra e evidência;
  - `grupos[]`, `errosCarga[]`, `cobertura` e `explicacao`.
- **Limite:** até `ANOMALIA_MAX_VENDAS` (200 mil) vendas; acima disso, 413.
- **Id do alerta:** de negócio (competência + grupo + matrícula + dia), igual entre reanálises; a versão dos dados fica em `versaoDados`.

### `POST /api/v2/executar-programa` (IA-10; produtor do código: BACK-9; consumidores: BACK-11 e apuração definitiva)

Contrato que o backend **já usa** no `AiServiceClient.executarProgramaPython` (`SimulacaoPythonOrquestradorService` e `CampanhaApuracaoService`). O backend gera e aprova `calcular_comissao(venda)` com as regras no código e consolida cenários e apuração em Java; a IA só executa o programa no sandbox, uma vez por item.

**Entrada** (campos extras ignorados):

```json
{
  "codigoFonte": "from decimal import Decimal, ROUND_HALF_UP\n\ndef calcular_comissao(venda: dict) -> float | None: ...",
  "contexto": {"modo": "SIMULACAO", "campanhaId": 42, "versaoCampanha": 3, "versaoProgramaPython": 2, "competencia": "2025-11"},
  "itens": [
    {"id": "<idVenda>#100", "venda": {"id_venda": "...", "data_venda": "2025-11-01", "valor_venda": 1200.0, "valor": 1200.0,
     "canal": "PADRAO", "cod_marca": 10, "cod_loja": 75, "cod_cargo": 100, "matricula": "MATRIC-1",
     "taxa_base": 0.025, "ignorar_vigencia": true}, "contexto": {"cenario": "100%", "fator": 1.0}}
  ]
}
```

- `calcular_comissao(venda)` ou `calcular_comissao(venda, contexto)`; o 2º argumento recebe o `contexto` do item (ou `{}`).
- A venda chega como o `montarVendaParaPython` serializa, sem conversão. Ids de item devem ser únicos (422 se repetidos).
- O código passa pela mesma análise estática por lista de permissão do `/simular` (imports, builtins, construções), com limite de tamanho próprio (`EXEC_MAX_CODE_LINES`/`EXEC_MAX_CODE_BYTES`), porque o programa do backend traz as regras embutidas.

**Saída 200:**

```json
{"sucesso": true, "motor": "PYTHON_SANDBOX", "totalItens": 9,
 "resultados": [{"id": "<idVenda>#100", "aplicada": true, "comissao": "42.00"}, {"id": "...", "aplicada": false, "comissao": null}],
 "erro": null, "detalhe": null, "violacoes": [], "assinaturaPrograma": "<sha256>", "contexto": {"modo": "SIMULACAO"}}
```

- `aplicada = false` quando o programa devolve `None` (nenhuma regra): o backend aplica a taxa contratual.
- `comissao` em texto, escala 2, HALF_UP. Retorno que não seja número/`None`, negativo ou não finito é falha.
- `assinaturaPrograma` = sha256 do `codigoFonte`, mesmo cálculo de `CampanhaProgramaPython.calcularChecksum` (BACK-9).
- Lote vazio (`itens: []`) responde 200 com `resultados: []`: o backend chama assim quando nenhuma venda é calculável.

**Falhas (fail-closed, sem resultado parcial):** 422 com o corpo acima (`sucesso: false`, `resultados: null`) mais `detail` e `error_code`. O backend lê `detalhe`/`detail` e `violacoes` e lança `BusinessException`.

| `error_code` | `erro` | Quando |
|---|---|---|
| `PROGRAMA_REJEITADO` | `VALIDACAO` | Sintaxe, import/builtin proibido, função ausente ou assinatura errada |
| `PROGRAMA_FALHOU` | `ERRO_CODIGO` | Exceção em um item (`detalhe` cita o id do item) |
| `PROGRAMA_FALHOU` | `TIMEOUT`, `MEMORIA`, `VIOLACAO`, `SAIDA_EXCESSIVA`, `SAIDA_INVALIDA` | Limites do sandbox ou retorno inválido |

Acima de `EXEC_MAX_ITENS` (200 mil itens = 50 mil vendas × 4 cenários): 413 `VOLUME_EXCEDIDO`.

## 4. Erros

Todo erro HTTP tem o corpo `{"detail": "...", "error_code": "..."}` e traz `X-Correlation-Id`. O erro 422 inclui também `erros[{loc, msg, type}]`. O catálogo está em `src/app/core/erros.py`.

| `error_code` | HTTP | Ação no backend |
|---|---|---|
| `CHAVE_INTERNA_INVALIDA` | 401 | Configuração: chave/cabeçalho diferentes entre backend e IA. Não repetir |
| `AUTH_NAO_CONFIGURADA` | 503 | IA sem chave com `AI_INBOUND_AUTH_OBRIGATORIA=true` |
| `VALIDACAO_ENTRADA` | 422 | Payload inválido (ver `erros[]`). Não repetir igual |
| `NAO_ENCONTRADO` | 404 | Rota ou assinatura de programa inexistente |
| `METODO_NAO_PERMITIDO` | 405 | Método errado |
| `VOLUME_EXCEDIDO` | 413 | Recorte acima do limite configurado (`ANOMALIA_MAX_VENDAS`, `EXEC_MAX_ITENS`) |
| `PROGRAMA_REJEITADO` | 422 | `/executar-programa`: programa recusado pela análise estática. Corrigir e reaprovar |
| `PROGRAMA_FALHOU` | 422 | `/executar-programa`: erro em um item, limite de tempo/memória ou retorno inválido. Sem resultado parcial |
| `LLM_AUTH_ERROR` | 401 | Chave do provedor de LLM inválida (só rotas que usam LLM) |
| `LLM_RATE_LIMIT_ERROR` | 429 | Respeitar `Retry-After` |
| `LLM_TIMEOUT_ERROR` | 504 | Tentar mais tarde |
| `LLM_PROVIDER_ERROR` / `LLM_PARSING_ERROR` | 502 | Tentar mais tarde |
| `INTERNAL_ERROR` | 500 | Bug: registrar o `X-Correlation-Id` |

**Falhas de domínio respondem 200** e explicam o que faltou, sem inventar números:

- `pendencias[]`: `SIMULACAO_NAO_VALIDADA` deixa `resultados = []`; `CAMPO_AUSENTE`; `LIMITE_AGENTE_ATINGIDO`;
- `statusSugestoes = FALHA`, com `calibracoes[].status` = `FALHA` ou `SEM_SOLUCAO_VIAVEL`;
- grupos de anomalia com `AMOSTRA_INSUFICIENTE` ou `SEM_VARIACAO`.

**Indisponibilidade** (IA fora do ar ou recusando conexão) já é tratada no backend: o `AiServiceClient` lança `AiServiceUnavailableException`, e o timeout de leitura vira `AiTimeoutException`.

## 5. Timeouts em cascata

| Camada | Configuração | Padrão | Observação |
|---|---|---|---|
| Spring → IA | `AI_CONNECT_TIMEOUT` / `AI_READ_TIMEOUT` | 3 s / 60 s | Teto de qualquer rota |
| LLM (cada chamada) | `LLM_TIMEOUT_SECONDS` (+ espera de 429 ≤ `LLM_RATE_LIMIT_MAX_WAIT_SECONDS`) | 30 s (+5 s) | |
| Interpretação (agente) | `AGENT_MAX_DURATION_SECONDS` | 45 s | |
| Consulta IA → backend | `TOOL_TIMEOUT_SECONDS` | 5 s | |
| Execução no sandbox (cada) | `SIM_MAX_SECONDS` | 10 s | |
| Calibração (requisição inteira) | `CALIB_MAX_SEGUNDOS` | 20 s | Conferido antes de cada reexecução: pior caso ≈ 20 + 10 s |
| Execução do programa aprovado | `EXEC_MAX_SECONDS` | 30 s | Uma execução por chamada; 20 mil itens (5 mil vendas × 4 cenários) em ≈ 0,6 s |
| Anomalias | — | < 1 s para 30 mil vendas | Sem LLM nem sandbox |

**Pior caso de `/simular`:**

- **Template ou `codigoAprovado`:** 1 execução (≤ 10 s) + calibração (≤ 30 s) ≈ **40 s**, abaixo de 60 s.
- **Código livre gerado na própria chamada** (pedido com cálculo adicional, sem `codigoAprovado`):
  - 1 chamada ao LLM para cenários e até 2 para código, de 30 s cada;
  - sondas e execução (10 s cada);
  - calibração.

  **Pode passar de 60 s.** Por isso o BACK-11 deve chamar `/gerar-programa` na revisão técnica e depois `/simular` com `codigoAprovado` + `assinaturaPrograma`. Esse é o fluxo do BACK-9.

Medições:

- Simulação com calibração em NOV/25 real (4.973 vendas, 3 cenários excedidos): **8,7 s**.
- Anomalias em JUL/25 e NOV/25: **0,04 s**.

## 6. Integração com o backend

Situação do `dev` do backend em 15/11/2026 (PR #34, BACK-9/BACK-11 mergeados):

| Fluxo do backend | Rota da IA | Situação |
|---|---|---|
| Simulação dos 4 cenários (`SimulacaoPythonOrquestradorService`) e apuração definitiva (`CampanhaApuracaoService`) | `POST /api/v2/executar-programa` | **Atendido por esta entrega.** O backend gera o programa, consolida os cenários em Java e só pede à IA a comissão de cada item |
| Calibração e explicações (IA-6/IA-7) para o FRONT-8 | `POST /api/v2/simular` com `calibrar=true` | Método `AiServiceClient.simularV2` pronto; falta o BACK-11 chamá-lo (Davi) |
| Anomalias para o FRONT-6 (IA-8) | `POST /api/v2/anomalias/analisar` | Método `AiServiceClient.analisarAnomaliasV2` pronto; a branch `feat/anomaly-analysis` (Ygor) ainda calcula z-score em Java |
| Geração do programa pela IA (IA-2) | `POST /api/v2/gerar-programa` | Método `AiServiceClient.gerarProgramaV2` pronto; hoje o BACK-9 gera o código em Java |

**O que mudou no backend nesta entrega** (branch `feature/ia10-cliente-ia-correlacao`, só no `AiServiceClient`, sem alterar o comportamento dos fluxos existentes):

1. `X-Correlation-Id` em todas as chamadas à IA, com log do id e da rota;
2. `gerarProgramaV2`, `simularV2` e `analisarAnomaliasV2`, com a mesma chave interna e o mesmo tratamento de indisponibilidade e timeout; um 4xx da IA (payload inválido, volume acima do limite) vira `BusinessException` com a mensagem da IA;
3. rotas configuráveis: `ai.service.v2.gerar-programa-endpoint`, `ai.service.v2.simular-endpoint`, `ai.service.v2.anomalias-endpoint`;
4. `AiServiceClientContratoIaTest` cobre rotas, cabeçalhos, 4xx/5xx e a resposta do `executar-programa` com os campos extras da IA.

**Para o IA-6/IA-7 chegarem à tela (BACK-11):** o programa do backend tem as regras escritas no código, então a calibração não consegue reexecutá-lo com parâmetros alterados. O caminho é o BACK-11 chamar `simularV2` com as regras da proposta, o recorte do BACK-10 (`vendas`, `taxasContratuais`, `pendenciasAceitas`, `versoesFontes`), `orcamento`, `periodoCampanha` e `calibrar=true`, e persistir `calibracoes[]`, `explicacoes[]`, `assinaturaPrograma`, `versaoFontes.recorte` e `contexto` junto com a execução.

**Para o IA-8 chegar à tela (BACK-12):** chamar `analisarAnomaliasV2` com `competencia`, `vendas` e `dadosRh` do recorte e persistir `alertas[]` pelo `id` (estável entre reanálises), `versaoDados` e `metodo`.

**Compatibilidade verificada:**

- `tests/test_contrato_sprint3.py`: o payload com **todos** os campos de `VendaRecorteIaDTO`, `ColaboradorRhRecorteIaDTO`, `TaxaContratualRecorteIaDTO`, `PendenciaAceitaRecorteIaDTO` e `VersoesFontesRecorteIaDTO` (como o Jackson serializa) é aceito por `/simular` e `/anomalias/analisar`, e os identificadores e hashes voltam na resposta;
- `tests/test_executar_programa.py`: programa no formato exato do `gerarCodigoConsolidado` e itens no formato do `montarVendaParaPython`, nos modos `SIMULACAO` (4 itens por venda) e `APURACAO` (vigência respeitada), lote vazio, falhas e limites.

## 7. Roteiro de demonstração (bases do IA-9)

1. Gerar as bases limpas: `python scripts/bases_limpas/gerar.py --origem "../Base Dom Rock" --destino data/bases_limpas`. Importá-las no backend.
2. **Simulação e apuração pelo backend:** aprovar o programa Python da campanha (BACK-9) e rodar a simulação Python (BACK-11). As chamadas chegam em `/api/v2/executar-programa` com o mesmo `X-Correlation-Id` nos logs dos dois lados. Na coleção: pasta "executar-programa".
3. **4 cenários com orçamento:** requisição "Simular — 4 cenários com orçamento" da coleção, ou uma campanha real pelo backend.
4. **Cenário excedido com sugestão:** `calibrar: true`. Espera-se `SUGESTAO_VALIDADA` com parâmetros antes/depois.
5. **Sem sugestão viável:** orçamento abaixo da parcela contratual. Espera-se `SEM_SOLUCAO_VIAVEL`.
6. **Anomalias** de JUL/25 a partir do recorte: MATRIC-141 aparece como alerta.
7. **Falhas:**
   - IA parada → `AiServiceUnavailableException`;
   - `AI_READ_TIMEOUT` baixo → `AiTimeoutException`;
   - chave diferente → 401 `CHAVE_INTERNA_INVALIDA`.
