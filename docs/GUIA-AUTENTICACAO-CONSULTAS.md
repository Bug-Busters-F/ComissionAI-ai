# Autenticação das consultas da IA ao backend

Configurar `AI_SERVICE_API_KEY` com o mesmo segredo do backend do PR #33. O cabeçalho padrão é `X-Internal-Api-Key`; se alterado, definir `AI_SERVICE_AUTH_HEADER` igual nos dois serviços. Reiniciar a IA após mudar as variáveis.

O cliente `BackendClient` inclui a chave nas chamadas GET/POST de `/api/v1/consultas-ia`. Não utiliza a senha/token pessoal de um usuário, não segue redirecionamentos e não coloca a chave em mensagens de erro. Falha 401/403 continua sendo falha de consulta, sem resposta de sucesso ou ausência de dados simulada e sem repetição automática.

Sem chave, o cliente permanece compatível com ambientes antigos sem autenticação; o backend novo rejeita essas consultas. Para o backend protegido, a configuração da chave é obrigatória. Nunca disponibilizar essa variável ao frontend.

Essa mudança autentica chamadas de saída; ela não implementa proteção das rotas de entrada da API Python. Testes controlados em `tests/test_backend_auth.py`, sem chamadas ao provedor de linguagem.

Verificação: suíte completa com 322 testes aprovados (incluindo quatro testes novos), sem usar o modelo real. A integração com o backend em execução permanece para validação após configurar a mesma chave nos dois serviços.
