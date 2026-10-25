# Exemplos de interpretação v2 (IA-2)

Gerado a partir do extrator real (`ExtratorCampanha`) com a **saída bruta do LLM simulada** (mostrada em cada exemplo). Mostra o que a normalização determinística faz com a extração: dimensões resolvidas, taxa, faixa, bônus, vigência herdada, origem rastreável e pendências. Data de referência: 2026-09-07; catálogo: marcas PRETO/BRANCO; cargos 100 VENDEDOR LOJA, 150 GERENTE DE LOJA, 151 GERENTE QUIOSQUE.

## 1. Regra simples

**Pedido:** Pagar 5% no canal ecommerce durante dezembro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "Pagar 5% no canal ecommerce", "taxa_raw": "5%", "canal": "ECOMMERCE"}], "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "canal": "ECOMMERCE"
 },
 "taxa": "0.0500",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "Pagar 5% no canal ecommerce",
 "pendencias": []
}
```

## 2. Duas regras por público (cargo ambíguo vira pendência)

**Pedido:** 3% para vendedores da loja 75 e 2% para gerentes da loja 75 em dezembro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "3% para vendedores da loja 75", "taxa_raw": "3%", "cargo_raw": "vendedores", "loja_raw": "75"}, {"trecho_origem": "2% para gerentes da loja 75", "taxa_raw": "2%", "cargo_raw": "gerentes", "loja_raw": "75"}], "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA",
  "codLoja": 75
 },
 "taxa": "0.0300",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "3% para vendedores da loja 75",
 "pendencias": []
}
```
```json
{
 "idLocal": "p2",
 "condicoes": {
  "codLoja": 75
 },
 "taxa": "0.0200",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "2% para gerentes da loja 75",
 "pendencias": [
  "AMBIGUIDADE_CARGO: Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'."
 ]
}
```

## 3. Canal e loja distintos

**Pedido:** 5% no ecommerce e 4% na loja 12 em outubro de 2026

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "5% no ecommerce", "taxa_raw": "5%", "canal": "ECOMMERCE"}, {"trecho_origem": "4% na loja 12", "taxa_raw": "4%", "loja_raw": "12"}], "vigencia_inicio_raw": "outubro de 2026", "vigencia_fim_raw": "outubro de 2026"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "canal": "ECOMMERCE"
 },
 "taxa": "0.0500",
 "vigencia": [
  "2026-10-01",
  "2026-10-31"
 ],
 "origem": "5% no ecommerce",
 "pendencias": []
}
```
```json
{
 "idLocal": "p2",
 "condicoes": {
  "codLoja": 12
 },
 "taxa": "0.0400",
 "vigencia": [
  "2026-10-01",
  "2026-10-31"
 ],
 "origem": "4% na loja 12",
 "pendencias": []
}
```

## 4. Comissão individual com bônus de valor fixo

**Pedido:** A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda em outubro de 2026

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda", "matricula_raw": "MATRIC-56", "taxa_raw": "6%", "bonus_valor_raw": "R$ 200"}], "vigencia_inicio_raw": "outubro de 2026", "vigencia_fim_raw": "outubro de 2026"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "matricula": "MATRIC-56"
 },
 "taxa": "0.0600",
 "bonus": {
  "valorFixo": "200.00"
 },
 "vigencia": [
  "2026-10-01",
  "2026-10-31"
 ],
 "origem": "A matrícula MATRIC-56 ganha 6% mais um bônus de R$ 200 por venda",
 "pendencias": []
}
```

## 5. Bônus percentual

**Pedido:** Vendedores da marca PRETO ganham 3% mais 1% de bônus sobre a venda em novembro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "Vendedores da marca PRETO ganham 3% mais 1% de bônus sobre a venda", "cargo_raw": "Vendedores", "marca_raw": "PRETO", "taxa_raw": "3%", "bonus_percentual_raw": "1%"}], "vigencia_inicio_raw": "novembro", "vigencia_fim_raw": "novembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codMarca": 10,
  "descrMarca": "PRETO",
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA"
 },
 "taxa": "0.0300",
 "bonus": {
  "percentual": "0.0100"
 },
 "vigencia": [
  "2026-11-01",
  "2026-11-30"
 ],
 "origem": "Vendedores da marca PRETO ganham 3% mais 1% de bônus sobre a venda",
 "pendencias": []
}
```

## 6. Faixas de valor contíguas

**Pedido:** 2% nas vendas até R$ 10 mil e 3% nas vendas acima de R$ 10 mil no ecommerce em dezembro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "2% nas vendas até R$ 10 mil", "taxa_raw": "2%", "canal": "ECOMMERCE", "faixa_max_raw": "R$ 10 mil", "faixa_max_inclusivo": true}, {"trecho_origem": "3% nas vendas acima de R$ 10 mil", "taxa_raw": "3%", "canal": "ECOMMERCE", "faixa_min_raw": "R$ 10 mil", "faixa_min_inclusivo": false}], "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "canal": "ECOMMERCE",
  "faixaValor": {
   "campo": "VENDA",
   "max": "10000.00",
   "minInclusivo": true,
   "maxInclusivo": true
  }
 },
 "taxa": "0.0200",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "2% nas vendas até R$ 10 mil",
 "pendencias": []
}
```
```json
{
 "idLocal": "p2",
 "condicoes": {
  "canal": "ECOMMERCE",
  "faixaValor": {
   "campo": "VENDA",
   "min": "10000.00",
   "minInclusivo": false,
   "maxInclusivo": false
  }
 },
 "taxa": "0.0300",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "3% nas vendas acima de R$ 10 mil",
 "pendencias": []
}
```

## 7. Pedido parcialmente mensurável (nada é descartado)

**Pedido:** 5% para quem bater a meta da loja 12. Os gerentes também ganham. Em dezembro.

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "5% para quem bater a meta da loja 12", "taxa_raw": "5%", "loja_raw": "12", "criterios_nao_suportados": ["meta de faturamento"]}, {"trecho_origem": "Os gerentes também ganham", "cargo_raw": "gerentes"}], "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codLoja": 12
 },
 "taxa": "0.0500",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "5% para quem bater a meta da loja 12",
 "pendencias": [
  "CRITERIO_NAO_SUPORTADO: Critério não suportado no MVP: meta de faturamento."
 ]
}
```
```json
{
 "idLocal": "p2",
 "condicoes": {},
 "taxa": null,
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "Os gerentes também ganham",
 "pendencias": [
  "AMBIGUIDADE_CARGO: Ambiguidade de cargo: 'gerentes' pode referir-se a 'GERENTE DE LOJA' ou 'GERENTE QUIOSQUE'.",
  "CAMPO_AUSENTE: Taxa/percentual de comissão não identificado no trecho."
 ]
}
```

## 8. Ajuste sobre a base (a conta é do IA-5)

**Pedido:** Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a comissão base em novembro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a comissão base", "cargo_raw": "Vendedores", "marca_raw": "PRETO", "operacao_raw": "mais 1 ponto percentual sobre a comissão base"}], "vigencia_inicio_raw": "novembro", "vigencia_fim_raw": "novembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codMarca": 10,
  "descrMarca": "PRETO",
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA"
 },
 "taxa": null,
 "vigencia": [
  "2026-11-01",
  "2026-11-30"
 ],
 "origem": "Vendedores da marca PRETO ganham mais 1 ponto percentual sobre a comissão base",
 "pendencias": [
  "CAMPO_AUSENTE: Ajuste sobre a taxa base ('mais 1 ponto percentual sobre a comissão base') depende da comissão base; a taxa final ainda não foi calculada."
 ]
}
```

## 9. Vigência incompatível com a da campanha

**Pedido:** 3% para vendedores em janeiro

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "3% para vendedores em janeiro", "taxa_raw": "3%", "cargo_raw": "vendedores", "vigencia_inicio_raw": "janeiro", "vigencia_fim_raw": "janeiro"}]}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA"
 },
 "taxa": "0.0300",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "3% para vendedores em janeiro",
 "pendencias": [
  "VIGENCIA_INCOMPATIVEL: O pedido cita para esta regra o período 2026-01-01 a 2026-01-31, diferente da vigência comum da campanha (2026-12-01 a 2026-12-31). Foi mantida a vigência da campanha."
 ]
}
```

## 10. Trecho sem regra vira trecho não mapeado

**Pedido:** 3% para vendedores da loja 75 em dezembro. Pagar também pelos produtos da categoria calçados

**Saída bruta do LLM (simulada):**
```json
{"regras": [{"trecho_origem": "3% para vendedores da loja 75 em dezembro", "taxa_raw": "3%", "cargo_raw": "vendedores", "loja_raw": "75"}], "vigencia_inicio_raw": "dezembro", "vigencia_fim_raw": "dezembro"}
```

**Propostas:**

```json
{
 "idLocal": "p1",
 "condicoes": {
  "codCargo": 100,
  "descriCargo": "VENDEDOR LOJA",
  "codLoja": 75
 },
 "taxa": "0.0300",
 "vigencia": [
  "2026-12-01",
  "2026-12-31"
 ],
 "origem": "3% para vendedores da loja 75 em dezembro",
 "pendencias": []
}
```

**Trechos não mapeados:** `Pagar também pelos produtos da categoria calçados`
