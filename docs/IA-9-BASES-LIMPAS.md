# IA-9 — Bases limpas de RH e Vendas (JUL a DEZ/2025)

Gera versões consistentes dos 12 arquivos de RH e Vendas, preservando os originais, com registro de toda correção e pendência. Nenhum valor de negócio é fabricado.

## Como executar

```bash
pip install openpyxl   # dependência apenas do script, não do serviço
python scripts/bases_limpas/gerar.py --origem "../Base Dom Rock" --destino data/bases_limpas
```

`data/bases_limpas/` está no `.gitignore`: os dados do cliente não são versionados, só o script que os gera. A execução é determinística: rodar duas vezes produz o mesmo `hashConteudo` e o mesmo `registro_correcoes.csv`.

| Saída | Conteúdo |
|---|---|
| `rh/RH_AAAA-MM.xlsx`, `vendas/VENDAS_AAAA-MM.xlsx` | Bases para o importador do backend: cabeçalho na linha 1 e colunas na mesma ordem lida por `HrFileRowMapper`/`SalesFileRowMapper` |
| `csv/*.csv` | Mesmos dados em CSV (`;`, UTF-8), para testes e análises (IA-5, IA-8) |
| `registro_correcoes.csv` | Uma linha por ajuste, remoção ou pendência: arquivo, linha original, matrícula, tipo, ação, regra, campo, antes, depois e justificativa |
| `resumo.json` | Por arquivo: linhas lidas, mantidas, removidas por regra, pendências e hash do conteúdo |

Invariante verificada em toda execução: **linhas lidas = mantidas + removidas**.

## Regras

| Regra | Tipo | Ação | Critério |
|---|---|---|---|
| `CABECALHO_PADRONIZADO` | Normalização | Altera | `Matricula `, `Cod_Cargo `, `Vlr _Venda` etc. → nome sem espaço; ordem preservada |
| `COLUNA_FORA_DO_LAYOUT` | Normalização | Remove a coluna | Ex.: `VENDAS R$` no RH de SET |
| `VALOR_ARREDONDADO` | Normalização | Altera | Valor com mais de 2 casas → HALF_UP 2 casas (mesma escala do backend) |
| `ERRO_ESTRUTURAL` | Erro | Remove a linha | O que o backend trata como impeditivo: campo obrigatório ausente, valor ≤ 0, data fora da competência, demissão antes da admissão |
| `RH_DUPLICADO` | Duplicidade | Remove a cópia | Linha de RH idêntica a outra |
| `RH_MATRICULA_REPETIDA_DIVERGENTE` | Pendência | Mantém | Mesma matrícula com dados diferentes (exige decisão humana) |
| `VENDA_SEM_RH` | Erro | Remove a linha | Matrícula ausente do RH da competência (**decisão do PO**). A justificativa diz em quais outros meses a matrícula aparece |
| `VENDA_DUPLICADA` | Duplicidade | Remove a cópia | Mesma matrícula, data, loja, marca e valor (chave do `SalesRowValidator`); conta uma vez (**decisão do PO**) |
| `LOJA_DIVERGENTE_RH` | Pendência | Mantém | Loja da venda ≠ loja do colaborador (pode ser atendimento em outra loja) |
| `MARCA_DIVERGENTE_RH` | Pendência | Mantém | Marca da venda ≠ marca do colaborador (afeta a taxa contratual) |
| `VENDA_APOS_DEMISSAO` | Pendência | Mantém | Data da venda posterior à demissão |
| `VENDA_ANTES_ADMISSAO` | Pendência | Mantém | Venda em competência anterior à admissão. Venda datada no dia 1º com admissão no mesmo mês **não** conta, porque a data representa a competência |
| `SEM_TAXA_CONTRATUAL` | Pendência | Mantém | Marca + cargo + descrição do cargo sem taxa no `BASE_COMMISS` (a descrição separa GERENTE DE LOJA de GERENTE QUIOSQUE, ambos código 150) |
| `CADASTRO_INCONSISTENTE` | Pendência | Mantém | Um código de marca/loja com descrições diferentes, ou loja associada a mais de uma marca, entre todas as bases |

Vendas fora do padrão estatístico (como as de JUL, com máximo de R$ 78.542) são preservadas: são material do IA-8.

## Resultado sobre os arquivos da Dom Rock (14/11/2026)

| Arquivo | Lidas | Mantidas | Removidas | Pendências |
|---|---|---|---|---|
| RH JUL | 322 | 322 | — | — |
| Vendas JUL | 5.018 | 4.984 | 34 duplicadas | 164 loja ≠ RH |
| RH AGO | 465 | 465 | — | — |
| Vendas AGO | 5.000 | 4.937 | 45 duplicadas, 18 sem RH | 12 loja ≠ RH, 4 marca ≠ RH |
| RH SET | 468 | 467 | 1 duplicada (MATRIC-246) | — (coluna `VENDAS R$` removida) |
| Vendas SET | 5.000 | 4.946 | 48 duplicadas, 6 sem RH | 30 loja ≠ RH |
| RH OUT | 460 | 460 | — | — |
| Vendas OUT | 5.000 | 4.945 | 54 duplicadas, 1 sem RH | 5 loja ≠ RH |
| RH NOV | 469 | 469 | — | — |
| Vendas NOV | 5.000 | 4.973 | 25 duplicadas, 2 sem RH | 14 loja ≠ RH, 8 após demissão |
| RH DEZ | 467 | 467 | — | — |
| Vendas DEZ | 5.000 | 4.939 | 28 duplicadas, 33 sem RH | 15 loja ≠ RH, 3 marca ≠ RH |

Sem erros estruturais, sem pendências de taxa contratual e sem cadastros inconsistentes entre as bases.

## Validação no backend (pendente)

Importar os 12 arquivos de `rh/` e `vendas/` pelo fluxo normal de importação (RH antes de Vendas em cada competência) e confirmar zero impeditivos. Os avisos esperados são os já registrados como pendência (loja/marca divergente, venda após demissão).

## Testes

`tests/test_bases_limpas.py` usa dados sintéticos (nenhum dado do cliente) e cobre cada regra acima, a invariante de totais, o determinismo do hash e a geração ponta a ponta sem alterar os originais.
