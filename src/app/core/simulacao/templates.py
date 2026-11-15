"""
Template de simulação para casos genéricos.

Código FIXO (não gerado por LLM) que também passa pela análise estática e roda no sandbox.
Regras de negócio espelhadas do Spring (`SimulacaoCenariosService`/`ReferenciaPublicoService`):
- uma única regra por venda, a de maior especificidade (matrícula 16, loja 8, cargo 4, canal 2, marca 1);
  a faixa de valor desempata (+0.5); empate no topo = conflito (a venda não é calculada e é contada);
- venda do público sem regra aplicável na faixa usa a taxa contratual (`taxaContratual`), agrupada em
  `porBloco["BASE_CONTRATUAL"]`; sem taxa contratual a venda também não é calculada e é contada (IA-5);
- `contratualEmConflito` = custo contratual das vendas em conflito, para o custo contratual comparar só as
  vendas calculadas;
- comissão = valor×taxa + valor×bônus% + bônus fixo, cada parcela HALF_UP escala 2;
- o cenário multiplica o valor de cada venda (HALF_UP escala 2) e as faixas são reavaliadas pelo valor
  escalado; `vendasMudancaFaixa` conta as vendas cuja regra muda em relação ao valor original (100%).
"""

TEMPLATE_CODIGO = '''
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
PESOS = (("matricula", 16), ("codLoja", 8), ("codCargo", 4), ("canal", 2), ("codMarca", 1))
CONTRATUAL = "BASE_CONTRATUAL"


def _q(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _em_faixa(valor, f):
    if f is None:
        return True
    mn = f.get("min")
    mx = f.get("max")
    if mn is not None and (valor < mn if f.get("minInclusivo", True) else valor <= mn):
        return False
    if mx is not None and (valor > mx if f.get("maxInclusivo", False) else valor >= mx):
        return False
    return True


def _pontuar(venda, valor, regra):
    c = regra.get("condicoes") or {}
    pontos = Decimal("0")
    for chave, peso in PESOS:
        alvo = c.get(chave)
        if alvo is None:
            continue
        atual = venda.get(chave)
        if chave == "canal":
            alvo = alvo.upper()
            atual = (atual or "PADRAO").upper()
        if alvo != atual:
            return None
        pontos += peso
    data = venda.get("dataVenda")
    ini = regra.get("dataInicio")
    fim = regra.get("dataFim")
    if data is not None and ((ini is not None and data < ini) or (fim is not None and data > fim)):
        return None
    faixa = c.get("faixaValor")
    if not _em_faixa(valor, faixa):
        return None
    if faixa is not None:
        pontos += Decimal("0.5")
    return pontos


def _escolher(venda, valor, regras):
    melhor = None
    melhores = []
    for regra in regras:
        p = _pontuar(venda, valor, regra)
        if p is None:
            continue
        if melhor is None or p > melhor:
            melhor = p
            melhores = [regra]
        elif p == melhor:
            melhores.append(regra)
    if not melhores:
        return CONTRATUAL, None
    if len(melhores) > 1:
        return None, None
    return melhores[0].get("idLocal", "?"), melhores[0]


def _comissao(valor, regra):
    total = Decimal("0")
    if regra.get("taxa") is not None:
        total += _q(valor * regra["taxa"])
    bonus = regra.get("bonus") or {}
    if bonus.get("percentual") is not None:
        total += _q(valor * bonus["percentual"])
    if bonus.get("valorFixo") is not None:
        total += _q(bonus["valorFixo"])
    return total


def simular(vendas, regras, cenario):
    mult = cenario.get("multiplicadorVendas", Decimal("1"))
    total_vendas = Decimal("0")
    total_comissao = Decimal("0")
    por_bloco = {}
    por_matricula = {}
    n = {"regra": 0, "contratual": 0, "conflito": 0, "sem": 0, "mudou": 0}
    contratual_conflito = Decimal("0")
    for venda in vendas:
        valor = _q(venda["valorVenda"] * mult)
        total_vendas += valor
        chave, regra = _escolher(venda, valor, regras)
        if mult != 1 and chave != _escolher(venda, _q(venda["valorVenda"]), regras)[0]:
            n["mudou"] += 1
        if chave is None:
            n["conflito"] += 1
            if venda.get("taxaContratual") is not None:
                contratual_conflito += _q(valor * venda["taxaContratual"])
            continue
        if regra is None:
            taxa = venda.get("taxaContratual")
            if taxa is None:
                n["sem"] += 1
                continue
            c = _q(valor * taxa)
            n["contratual"] += 1
        else:
            c = _comissao(valor, regra)
            n["regra"] += 1
        total_comissao += c
        por_bloco[chave] = por_bloco.get(chave, Decimal("0")) + c
        mat = venda.get("matricula", "?")
        por_matricula[mat] = por_matricula.get(mat, Decimal("0")) + c
    return {
        "cenario": cenario.get("nome", ""),
        "totalVendas": _q(total_vendas),
        "totalComissao": _q(total_comissao),
        "porBloco": por_bloco,
        "porMatricula": por_matricula,
        "vendasComRegra": n["regra"],
        "vendasFallbackContratual": n["contratual"],
        "vendasEmConflito": n["conflito"],
        "vendasSemRegra": n["sem"],
        "vendasMudancaFaixa": n["mudou"],
        "contratualEmConflito": _q(contratual_conflito),
    }
'''
