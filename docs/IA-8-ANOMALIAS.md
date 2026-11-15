# IA-8 — Detecção estatística diária de anomalias

`POST /api/v2/anomalias/analisar` (consumidores: BACK-12 e FRONT-6) agrega as vendas por **colaborador/dia** e compara cada total com o do grupo comparável. Os totais fora da faixa esperada voltam como **indícios para conferência**.

O serviço é determinístico, não usa LLM e nunca altera ou exclui vendas.

## Entrada

Mesmo formato de `vendas` e `dadosRh` do recorte do backend (`RecortePopulacaoIaResponse`, BACK-10). Campos extras são ignorados.

```json
{
  "contexto": {"campanhaId": "1", "execucaoId": "e-123"},
  "competencia": "2025-07",
  "vendas": [{"id": "uuid", "matricula": "MATRIC-1", "codMarca": 10, "codCargo": 100, "descriCargo": "VENDEDOR LOJA", "valorVenda": 1234.50, "dataVenda": "2025-07-01"}],
  "dadosRh": [{"matricula": "MATRIC-1", "codCargo": 100, "descriCargo": "VENDEDOR LOJA"}],
  "parametros": {"k": 1.5, "amostraMinima": 8},
  "versaoFontes": {"hashRecorte": "…"}
}
```

- O cargo vem da venda. Se faltar, vem de `dadosRh`, com a matrícula comparada sem espaços e sem diferenciar maiúsculas.
- Quando `dadosRh` é informado, ele é a referência: venda de matrícula ausente nele é erro de carga.
- `parametros` é opcional. Os padrões vêm de `ANOMALIA_K` (1,5) e `ANOMALIA_AMOSTRA_MINIMA` (8), e os valores efetivos voltam em `metodo`.
- Acima de `ANOMALIA_MAX_VENDAS` (200 mil) a rota responde 413.

## Método

| Item | Regra |
|---|---|
| Observação | Total vendido pelo colaborador no dia. Dia sem venda **não** vira zero |
| Grupo comparável | Marca + código do cargo + descrição do cargo (normalizada) + competência. 150 = GERENTE DE LOJA ≠ GERENTE QUIOSQUE |
| Quartis | Interpolação linear inclusiva (QUARTIL.INC do Excel e padrão do numpy), em `Decimal`, arredondados a centavos |
| Faixa | `[Q1 − k·IQR, Q3 + k·IQR]`. O mínimo fica em 0 quando o grupo não tem valores negativos (os quartis brutos ficam em `evidencia`) |
| Alerta | Total `> max` → `ACIMA_DA_FAIXA`; `< min` → `ABAIXO_DA_FAIXA` |

### Proteções contra alertas artificiais

| Situação | Tratamento |
|---|---|
| Grupo com menos de `amostraMinima` observações | `AMOSTRA_INSUFICIENTE`, sem faixa e sem alerta |
| IQR = 0 (valores repetidos) | `SEM_VARIACAO`, sem alerta |
| Venda sem RH/cargo | Erro de carga `VENDA_SEM_RH`, fora da análise |
| Venda sem marca | Erro de carga `VENDA_SEM_MARCA`, fora da análise |
| Data fora da competência | Erro de carga `FORA_DA_COMPETENCIA`, fora da análise |
| Dias sem nenhuma venda | Contados em `cobertura.diasSemCobertura` e citados em `observacoes`, nunca tratados como zero |

## Saída

**Campos da resposta:**

- `tipo = INDICIO_PARA_CONFERENCIA` e `aviso`;
- `granularidade = DIARIA`;
- `metodo{nome, k, amostraMinima, quartis, unidade, arredondamento}`;
- `versaoDados`: sha256 do recorte e dos parâmetros, independente da ordem das vendas;
- `versaoFontes`: ecoado da entrada;
- `execucaoId`;
- `resumo`, `grupos[]`, `alertas[]`, `errosCarga[]`, `cobertura`, `observacoes[]` e `explicacao`, esta determinística e com o verbo "conferir".

**Campos de cada alerta:**

- `id` de negócio (competência + grupo + matrícula + dia): não muda quando outras vendas da base são corrigidas, para o BACK-12 manter o vínculo do alerta já consultado. A versão exata dos dados está em `versaoDados`;
- `tipo`, `matricula`, `data`;
- `valorObservado`, `qtdVendas`, `vendaIds` (até 50);
- `faixaEsperada{min,max}` e `distanciaFaixa`;
- `grupo{codMarca, codCargo, descriCargo, competencia}` e `tamanhoAmostra`;
- `evidencia{q1, mediana, q3, iqr}`;
- `explicacao`.

## Resultados com as bases limpas (IA-9)

| Competência | Vendas | Observações colaborador/dia | Grupos (analisados / amostra insuficiente) | Alertas | Tempo |
|---|---|---|---|---|---|
| JUL/25 | 4.984 | 282 | 15 (5 / 10) | 6 | 0,04 s |
| NOV/25 | 4.973 | 981 | 14 (8 / 6) | 9 | 0,04 s |

**Observações sobre os dados:**

- **Data única no mês.** Fora de NOV, todas as vendas estão no dia 1º. Nesses meses, o total colaborador/dia coincide com o total mensal, e a resposta registra isso em `observacoes`.
- **A venda de R$ 78.542 de JUL não gera alerta.** Ela pertence à MATRIC-543, que soma R$ 85.000 no dia. Esse total fica dentro da faixa do grupo marca 10 / VENDEDOR LOJA (até R$ 173.236). O plano previa esse alerta a partir dos valores de **venda individual**. Pela agregação colaborador/dia pedida na tarefa (decisão de 14/11: só a análise diária), ele não é anômalo.
- O maior alerta de JUL é a MATRIC-141 (VENDEDOR BALCAO, marca 20): R$ 113.627,50 em 25 vendas, contra um limite de R$ 91.714,50.

## Testes

`tests/test_anomalias.py` cobre:

- quartis e reprodução da faixa a partir da evidência;
- alertas acima e abaixo da faixa;
- soma por colaborador/dia;
- separação dos grupos por descrição do cargo;
- grupo pequeno, IQR zero e dias sem cobertura;
- os erros de carga;
- o determinismo (ordem, hash e ids) e os parâmetros explícitos;
- 30 mil vendas;
- a rota (200, 413 e 422);
- o caso real de JUL, executado só quando as bases limpas estão presentes.
