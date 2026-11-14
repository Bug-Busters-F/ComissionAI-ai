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
| `X-Correlation-Id` | ida e volta | Opcional na ida (`[A-Za-z0-9._:-]{1,128}`); ausente ou inválido, a IA gera um. Sempre devolvido na resposta e presente em toda linha de log da requisição (`[id]`) |

A IA **não autentica usuários** e não tem cadastro próprio. Ela confia apenas no backend, pela chave interna, e registra o `usuarioSolicitanteId` que o backend repassa.

**Sem `AI_SERVICE_API_KEY`:**

- em desenvolvimento, as rotas ficam abertas e o log avisa na subida;
- em produção, use `AI_INBOUND_AUTH_OBRIGATORIA=true`: as rotas respondem 503 `AUTH_NAO_CONFIGURADA` até a chave existir.

## 2. Identificadores (`contexto`)

Aceito em `/gerar-programa`, `/simular` e `/anomalias/analisar`, e devolvido em `contexto` na resposta:

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

## 4. Erros

Todo erro HTTP tem o corpo `{"detail": "...", "error_code": "..."}` e traz `X-Correlation-Id`. O erro 422 inclui também `erros[{loc, msg, type}]`. O catálogo está em `src/app/core/erros.py`.

| `error_code` | HTTP | Ação no backend |
|---|---|---|
| `CHAVE_INTERNA_INVALIDA` | 401 | Configuração: chave/cabeçalho diferentes entre backend e IA. Não repetir |
| `AUTH_NAO_CONFIGURADA` | 503 | IA sem chave com `AI_INBOUND_AUTH_OBRIGATORIA=true` |
| `VALIDACAO_ENTRADA` | 422 | Payload inválido (ver `erros[]`). Não repetir igual |
| `NAO_ENCONTRADO` | 404 | Rota ou assinatura de programa inexistente |
| `METODO_NAO_PERMITIDO` | 405 | Método errado |
| `VOLUME_EXCEDIDO` | 413 | Recorte acima do limite configurado |
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

**BACK-11 (Davi)** — na branch `feat/versionar-programa-python`, o `SimulacaoPythonOrquestradorService` ainda executa o cálculo Java e só grava o motor `PYTHON_XAI_SANDBOX`. Para usar a IA, o `AiServiceClient` precisa de:

1. `gerarProgramaV2(payload)` → `POST /api/v2/gerar-programa`;
2. `simularV2(payload)` → `POST /api/v2/simular`, montando o payload a partir do `RecortePopulacaoIaResponse` conforme a tabela do §3;
3. `analisarAnomaliasV2(payload)` → `POST /api/v2/anomalias/analisar` (consumidor: BACK-12);
4. enviar `X-Correlation-Id` (por exemplo, o id da requisição do backend) e o `contexto` com `execucaoId` e `usuarioSolicitanteId`;
5. persistir `assinaturaPrograma`, `versaoFontes.recorte` e `contexto` da resposta junto com a execução.

Os métodos `postarV2` atuais já enviam a chave e tratam timeout e indisponibilidade. Basta reutilizá-los.

**Compatibilidade verificada** (`tests/test_contrato_sprint3.py`):

- o payload com **todos** os campos de `VendaRecorteIaDTO`, `ColaboradorRhRecorteIaDTO`, `TaxaContratualRecorteIaDTO`, `PendenciaAceitaRecorteIaDTO` e `VersoesFontesRecorteIaDTO` (como o Jackson serializa) é aceito pelas duas rotas;
- os identificadores e hashes voltam na resposta.

## 7. Roteiro de demonstração (bases do IA-9)

1. Gerar as bases limpas: `python scripts/bases_limpas/gerar.py --origem "../Base Dom Rock" --destino data/bases_limpas`. Importá-las no backend.
2. **4 cenários com orçamento:** requisição "Simular — 4 cenários com orçamento" da coleção, ou uma campanha real pelo backend.
3. **Cenário excedido com sugestão:** `calibrar: true`. Espera-se `SUGESTAO_VALIDADA` com parâmetros antes/depois.
4. **Sem sugestão viável:** orçamento abaixo da parcela contratual. Espera-se `SEM_SOLUCAO_VIAVEL`.
5. **Anomalias** de JUL/25 a partir do recorte: MATRIC-141 aparece como alerta.
6. **Falhas:**
   - IA parada → `AiServiceUnavailableException`;
   - `AI_READ_TIMEOUT` baixo → `AiTimeoutException`;
   - chave diferente → 401 `CHAVE_INTERNA_INVALIDA`.
