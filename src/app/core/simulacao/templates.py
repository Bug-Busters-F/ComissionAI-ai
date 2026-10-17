"""
Template de simulação para casos genéricos.

Código FIXO (não gerado por LLM) que também passa pela análise estática e roda no sandbox.
Regras de negócio espelhadas do Spring (`TaxaComissaoResolver`/`CalculoService`):
- uma única regra por venda, a de maior especificidade (matrícula 16, loja 8, cargo 4, canal 2, marca 1);
  a faixa de valor desempata (+0.5); empate no topo = conflito (a venda não recebe regra);
- comissão = valor×taxa + valor×bônus% + bônus fixo, cada parcela HALF_UP escala 2;
- o cenário multiplica o valor de cada venda (HALF_UP escala 2).
"""

TEMPLATE_CODIGO = '''
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def _q(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _em_faixa(valor, faixa):
    if faixa is None:
        return True
    mn = faixa.get("min")
    mx = faixa.get("max")
    if mn is not None:
        if faixa.get("minInclusivo", True):
            if valor < mn:
                return False
        else:
            if valor <= mn:
                return False
    if mx is not None:
        if faixa.get("maxInclusivo", False):
            if valor > mx:
                return False
        else:
            if valor >= mx:
                return False
    return True


def _pontuar(venda, valor, regra):
    c = regra.get("condicoes") or {}
    pontos = Decimal("0")
    if c.get("matricula") is not None:
        if c["matricula"] != venda.get("matricula"):
            return None
        pontos += 16
    if c.get("codLoja") is not None:
        if c["codLoja"] != venda.get("codLoja"):
            return None
        pontos += 8
    if c.get("codCargo") is not None:
        if c["codCargo"] != venda.get("codCargo"):
            return None
        pontos += 4
    if c.get("canal") is not None:
        canal_venda = (venda.get("canal") or "PADRAO").upper()
        if c["canal"].upper() != canal_venda:
            return None
        pontos += 2
    if c.get("codMarca") is not None:
        if c["codMarca"] != venda.get("codMarca"):
            return None
        pontos += 1
    data = venda.get("dataVenda")
    ini = regra.get("dataInicio")
    fim = regra.get("dataFim")
    if data is not None:
        if ini is not None and data < ini:
            return None
        if fim is not None and data > fim:
            return None
    faixa = c.get("faixaValor")
    if not _em_faixa(valor, faixa):
        return None
    if faixa is not None:
        pontos += Decimal("0.5")
    return pontos


def _comissao(valor, regra):
    total = Decimal("0")
    taxa = regra.get("taxa")
    if taxa is not None:
        total += _q(valor * taxa)
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
    sem_regra = 0
    conflitos = 0
    for venda in vendas:
        valor = _q(venda["valorVenda"] * mult)
        total_vendas += valor
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
            sem_regra += 1
            continue
        if len(melhores) > 1:
            conflitos += 1
            continue
        regra = melhores[0]
        c = _comissao(valor, regra)
        total_comissao += c
        idb = regra.get("idLocal", "?")
        por_bloco[idb] = por_bloco.get(idb, Decimal("0")) + c
        mat = venda.get("matricula", "?")
        por_matricula[mat] = por_matricula.get(mat, Decimal("0")) + c
    return {
        "cenario": cenario.get("nome", ""),
        "totalVendas": _q(total_vendas),
        "totalComissao": _q(total_comissao),
        "porBloco": por_bloco,
        "porMatricula": por_matricula,
        "vendasSemRegra": sem_regra,
        "vendasEmConflito": conflitos,
    }
'''
