# Guia rápido — consultas do agente e limite da Groq

Entrega em 22/10/2026. Alterações somente no repositório de IA, na branch local `fix/consultas-agente-rate-limit`, baseada na `dev` `1cbcd1c`. Sem commit/push automático.

## Verificação prévia de branches remotas

Foi executado `git fetch origin --prune` e conferida a lista real de heads remotos. As branches relacionadas eram:

- `feat/agente-multiplas-regras-e-simulacao` (`81bd13f`): introduz o agente e os contratos; incorporada à dev pelo PR #10.
- `fix/agente-pendencias-e-schema-groq` (`48abd35`): preserva pendências por bloco em interrupções e corrige o schema da Groq; incorporada à dev pelo PR #11.

Ambas já estão contidas na dev; não havia uma branch remota com correção de consumo de chamadas ou espera de rate limit. As proteções existentes de pendências e schema foram mantidas.

## O que mudou

1. **Consultas sem nova decisão de LLM por padrão.** Após extrair as regras, o Python resolve cadastro, matrícula, base e concorrência com os argumentos já conhecidos. A normalização, as regras de dependência e a validação das ferramentas continuam ativas. Ambiguidades e falhas reais continuam visíveis.
2. **Cache aplicado antes de consumir novo orçamento.** Resultados de consultas idênticas são aplicados a cada bloco com sua própria evidência. O reaproveitamento não consome um novo passo/chamada de ferramenta e funciona mesmo quando o limite de novas consultas foi alcançado. O limite de duração continua sendo respeitado.
3. **429 com espera limitada.** A Groq é retentada uma vez por padrão apenas quando existe `Retry-After` válido, a espera não supera 5s e cabe no timeout restante. Sem prazo ou com espera longa, encerra com erro imediatamente. Não há espera de minutos nem sucesso simulado.
4. **Prazo informado na resposta.** Quando disponível, `Retry-After` é enviado no HTTP 429 da IA e o detalhe explica a espera. Credenciais e o corpo bruto do erro da Groq não são expostos nesse tratamento. Permissão/autenticação não são retentadas.
5. **Fallback IPv4 com orçamento restante.** A segunda tentativa não reinicia o timeout completo. O fallback existente de conectividade é preservado.

## Como habilitar

Os padrões novos já estão no código; não é necessário editar a chave existente. As opções também estão em `.env.example`:

```dotenv
AGENT_USE_LLM_DECISIONS=false
LLM_RATE_LIMIT_MAX_RETRIES=1
LLM_RATE_LIMIT_MAX_WAIT_SECONDS=5
LLM_TIMEOUT_SECONDS=30
```

- `AGENT_USE_LLM_DECISIONS=true` mantém o modo anterior, com decisões por modelo. Use apenas se precisar desse comportamento; ele volta a consumir chamadas adicionais.
- `LLM_RATE_LIMIT_MAX_RETRIES=0` desabilita a retentativa de 429. Valores aceitos: 0 a 2.
- `LLM_RATE_LIMIT_MAX_WAIT_SECONDS` aceita de 0 a 30 segundos. O tempo restante da chamada também limita a espera.

Com `--reload`, as mudanças Python são recarregadas pelo Uvicorn. Se alterar variáveis do `.env` ou executar sem reload, reinicie o processo. O comando permanece:

```bash
python -m uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000 --reload
```

O frontend continua chamando o backend, que usa `POST /api/v2/interpretar`. Nenhuma mudança de payload ou de endpoint é necessária.

## Como conferir

No frontend, interprete novamente:

> A campanha será válida de 01/10/2026 a 31/10/2026. Para vendas no canal LOJA_FISICA com valor inferior a R$ 1.000,00, a comissão será de 3,5%. Para vendas no canal LOJA_FISICA com valor maior ou igual a R$ 1.000,00, a comissão será de 5%. Para vendas no canal BALCAO, a comissão será de 4%, sem restrição de valor.

Espere três blocos, com as faixas `< 1000` e `>= 1000`. Em uma interpretação bem-sucedida sem retentativas, a Groq recebe uma chamada para extração. As duas regras de loja física compartilham a consulta de concorrência, mantendo evidência separada nos blocos. A regra de balcão tem outra consulta. Não devem existir chamadas ao modelo apenas para escolher a próxima consulta.

Em caso de 429, aguarde o prazo informado antes de repetir. Repetições manuais frequentes continuam consumindo a cota da organização.

## Verificação realizada

- Antes da alteração: **237 testes passaram**.
- Depois: **260 testes passaram**, incluindo o modo anterior, o fluxo padrão com três regras/uma extração, 15 blocos reaproveitando uma consulta, limites de orçamento/duração, dependências de cadastros/base, preservação de ambiguidades, falhas por bloco, 429 e prazos inválidos/longos/esgotados, autenticação e HTTP Retry-After.
- Comando: `python -m unittest discover -s tests -v`, com o ambiente virtual ativo. Os testes automatizados não usam Groq real nem esperam os intervalos de retry.
- Teste manual real do agente com `openai/gpt-oss-20b` e backend local: **3,17s, uma requisição Groq HTTP 200, três regras, taxas 0.0350/0.0500/0.0400 e faixas corretas**. As três propostas ficaram sem pendências individuais de consulta; a trilha confirmou duas consultas distintas de concorrência e um reaproveitamento. O serviço manteve seu status geral `PROPOSTA_COM_PENDENCIAS`; o teste não equivale a salvar/aprovar uma campanha.
- O tratamento real de 429 não foi provocado artificialmente contra o provedor; foi validado por respostas controladas, sem gastar cota para induzir o erro.

## O que permanece para integração

- O backend ainda precisa encaminhar o status/`Retry-After` da IA caso se queira apresentar ao usuário uma espera exata. O frontend pode então distinguir limite de cota de indisponibilidade. Não houve alteração nesses repositórios nesta entrega.
- Quotas da organização continuam válidas. Limite diário, outros consumidores ou uma extração grande podem gerar 429 mesmo com a redução de chamadas.
- As operações de simulação, aceite e ativação da campanha continuam dependendo do backend atualizado e das bases de referência; esta correção trata a interpretação.
- A redução de chamadas não implementa, por si só, cálculo sobre a base ou geração de artefatos. Esses recursos dependem dos hooks e serviços específicos; a atualização abaixo registra a integração das implementações recebidas posteriormente da `dev`.

## Atualização da dev — 24/10/2026

A `dev` local e a branch `fix/consultas-agente-rate-limit` foram avançadas de `1cbcd1c` para `8ccc002` (merge do PR #12). As alterações locais foram preservadas em backup e stash, e reaplicadas sem conflitos textuais. Nenhum commit ou push adicional foi realizado.

Foram mantidos os novos hooks de ajuste sobre a base, explicações/Python, os serviços de reinterpretação e atualização de artefatos e as proteções de ambiguidade/versionamento trazidas pela `dev`. A configuração recomendada `LLM_MAX_OUTPUT_TOKENS=4096` também foi preservada. A configuração real de `.env` não foi alterada.

O único ajuste de compatibilidade foi no teste `test_llm_cai_apos_resolver_publico_preserva_loja`: ele agora habilita explicitamente `usar_llm_decisoes=True`, pois verifica a falha de uma chamada de decisão que não existe no modo determinístico padrão. O teste continua exigindo a falha e a preservação dos dados, e confere duas chamadas ao provedor. A cobertura do modo padrão permanece em `test_agente_deterministico.py` e nos testes integrados recebidos da `dev`.

O frontend continua usando a extração multirregras pelo backend. A existência de `/api/v2/reinterpretar` na IA não muda automaticamente o transporte do frontend ou o adaptador do backend.

Verificação após a integração: **318 testes passaram**, executados com `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src venv/bin/python -m unittest discover -s tests -v`; `git diff --check` aprovado e nenhum arquivo em conflito. Esses testes usam respostas controladas e não consomem a cota real da Groq. O serviço real não foi reiniciado nem recebeu novas requisições de interpretação para esta verificação.
