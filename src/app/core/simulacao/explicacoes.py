"""
Explicações por cenário com números verificáveis (IA-7 / BUG-120).

Cada explicação é montada SOMENTE a partir dos valores já calculados e validados (IA-5) e das
alternativas reexecutadas (IA-6). Nenhum LLM participa e o texto nunca recalcula nada:

- todo número citado em `resumo` ou `limitacoes` está em `numeros{}` (chave -> valor exato devolvido
  pela simulação), então o front pode destacar/conferir cada valor;
- `tipo` distingue sugestão validada por reexecução (SUGESTAO_VALIDADA) de ausência de solução
  (SEM_SOLUCAO_VIAVEL) e de falha na busca (SUGESTAO_INDISPONIVEL);
- cada explicação traz `execucaoId`, `assinaturaPrograma` e o cenário de origem.

Convenção de exibição: valores monetários em R$ (o sinal fica no texto: "a mais"/"a menos"),
taxas e fatores como percentual da fração guardada em `numeros`, percentuais já calculados
(`*Percentual*`) exibidos como estão.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.schemas.proposta import (
    Calibracao,
    ExplicacaoCenario,
    ItemExclusao,
    ResultadoCenario,
    ResumoOrcamento,
)

CONTRATUAL = "BASE_CONTRATUAL"

_ROTULO_CAMPO = {"taxa": "taxa", "bonus.percentual": "bônus percentual", "bonus.valorFixo": "bônus fixo"}

_EXCLUSOES = {
    "FORA_DO_PUBLICO": "venda(s) fora do público das regras não entram no cálculo",
    "SEM_TAXA_CONTRATUAL": "venda(s) do público sem taxa contratual cadastrada foram excluídas",
    "TAXA_CONTRATUAL_AMBIGUA": "venda(s) com taxa contratual ambígua (mesma marca e cargo) foram excluídas",
    "CONFLITO_REGRAS": "venda(s) com regras empatadas (conflito) ficaram sem valor",
}


class _Numeros:
    """Registra cada número citado e devolve o texto formatado a partir do MESMO valor."""

    def __init__(self) -> None:
        self.valores: dict[str, Decimal] = {}

    def _put(self, chave: str, valor: Decimal | int) -> Decimal:
        v = Decimal(valor)
        self.valores[chave] = v
        return v

    def moeda(self, chave: str, valor: Decimal) -> str:
        return _brl(abs(self._put(chave, valor)))

    def taxa(self, chave: str, valor: Decimal) -> str:
        """Fração (0,0458) exibida como percentual (4,58%)."""
        return f"{_dec_br(self._put(chave, valor) * 100)}%"

    def percentual(self, chave: str, valor: Decimal) -> str:
        """Valor já em pontos percentuais (78,13) exibido como 78,13%."""
        return f"{_dec_br(abs(self._put(chave, valor)))}%"

    def inteiro(self, chave: str, valor: int) -> str:
        return f"{self._put(chave, valor):,}".replace(",", ".")

    def decimal(self, chave: str, valor: Decimal) -> str:
        return _dec_br(self._put(chave, valor))


def gerar_explicacoes(
    resultados: list[ResultadoCenario],
    calibracoes: list[Calibracao],
    resumo: ResumoOrcamento | None,
    exclusoes: list[ItemExclusao],
    riscos: list[str],
    assinatura: str | None,
    execucao_id: str | None,
) -> list[ExplicacaoCenario]:
    """Uma explicação por cenário com números. Sem resultados validados, nada é explicado."""
    por_cenario = {c.multiplicadorVendas: c for c in calibracoes}
    saida: list[ExplicacaoCenario] = []
    for r in resultados:
        if r.custoProjetado is None or r.multiplicadorVendas is None:
            continue
        n = _Numeros()
        tipo, resumo_txt = _resumo(n, r, por_cenario.get(r.multiplicadorVendas), resumo)
        saida.append(ExplicacaoCenario(
            execucaoId=execucao_id,
            assinaturaPrograma=assinatura,
            cenario=r.cenario,
            multiplicadorVendas=r.multiplicadorVendas,
            tipo=tipo,
            resumo=resumo_txt,
            limitacoes=_limitacoes(n, r, resumo, exclusoes, riscos),
            numeros=n.valores,
        ))
    return saida


# ----------------------------------------------------------------------------- resumo
def _resumo(n: _Numeros, r: ResultadoCenario, cal: Calibracao | None,
            resumo: ResumoOrcamento | None) -> tuple[str, str]:
    assert r.custoProjetado is not None and r.multiplicadorVendas is not None
    partes = [
        f"Com vendas a {n.taxa('multiplicadorVendas', r.multiplicadorVendas)} do realizado, "
        f"o custo proposto no mês é {n.moeda('custoProposto', r.totalComissao)}"
    ]
    if r.custoContratual is not None and r.diferenca == 0:
        partes.append(f" (igual ao custo contratual de {n.moeda('custoContratual', r.custoContratual)})")
    elif r.custoContratual is not None and r.diferenca is not None:
        sentido = "a mais" if r.diferenca > 0 else "a menos"
        txt = (f" ({n.moeda('diferencaContratual', r.diferenca)} {sentido} que o custo contratual de "
               f"{n.moeda('custoContratual', r.custoContratual)}")
        if r.diferencaPercentual is not None:
            txt += f", {n.percentual('diferencaPercentual', r.diferencaPercentual)}"
        partes.append(txt + ")")
    proj = n.moeda("custoProjetado", r.custoProjetado)
    if r.fatorProjecao is not None:
        partes.append(f" e o custo projetado para a campanha é {proj} "
                      f"(fator de projeção {n.decimal('fatorProjecao', r.fatorProjecao)}).")
    else:
        partes.append(f" e o custo projetado para a campanha é {proj}.")
    texto = "".join(partes)

    enq = r.enquadramento
    if enq is None or enq.orcamentoTeto is None or enq.statusEnquadramento == "NAO_APLICAVEL":
        return "SEM_ORCAMENTO", texto + " Sem orçamento informado, não há enquadramento."

    teto = n.moeda("orcamento", enq.orcamentoTeto)
    uso = (f" ({n.percentual('percentualUsoOrcamento', enq.percentualUsoOrcamento)} do orçamento)"
           if enq.percentualUsoOrcamento is not None else "")
    if enq.dentroDoOrcamento:
        saldo = n.moeda("folga", enq.saldoOrcamento or Decimal("0"))
        tipo = "DENTRO_DO_ORCAMENTO"
        texto += f" Cabe no orçamento de {teto}, com folga de {saldo}{uso}."
        if _e_100(r) and resumo is not None and not resumo.aptoEncaminhamentoGerente:
            texto += " Ainda assim, o encaminhamento ao gerente está bloqueado (ver limitações)."
        return tipo, texto

    excesso = n.moeda("excesso", enq.excedenteOrcamento or Decimal("0"))
    texto += f" Excede o orçamento de {teto} em {excesso}{uso}."
    if cal is None:
        return "ACIMA_DO_ORCAMENTO", texto + " Nenhuma alternativa de ajuste foi solicitada para este cenário."
    if cal.status == "ENQUADRADA":
        return "SUGESTAO_VALIDADA", texto + " " + _sugestao(n, cal)
    if cal.status == "SEM_SOLUCAO_VIAVEL":
        return "SEM_SOLUCAO_VIAVEL", texto + " " + _sem_solucao(n, r, cal)
    return "SUGESTAO_INDISPONIVEL", texto + (
        " Não foi possível verificar uma alternativa dentro dos limites de reexecução; "
        "nenhuma sugestão foi gerada para este cenário."
    )


def _sugestao(n: _Numeros, cal: Calibracao) -> str:
    assert cal.custoProjetadoRecalculado is not None and cal.fatorAjuste is not None
    itens = []
    for a in cal.alteracoes:
        chave = f"{a.idLocal}.{a.campo}"
        fmt = n.moeda if a.campo == "bonus.valorFixo" else n.taxa
        itens.append(f"{_ROTULO_CAMPO[a.campo]} da regra \"{a.idLocal}\" de {fmt(chave + '.antes', a.antes)} "
                     f"para {fmt(chave + '.depois', a.depois)}")
    return (
        f"Alternativa validada por reexecução do mesmo programa: reduzir {_lista(itens)} "
        f"({n.taxa('fatorAjuste', cal.fatorAjuste)} dos valores originais). "
        f"Custo projetado recalculado: {n.moeda('custoProjetadoRecalculado', cal.custoProjetadoRecalculado)}, "
        f"folga de {n.moeda('folgaAlternativa', cal.folga or Decimal('0'))}. "
        "Aplicar a alternativa exige revisar e simular de novo a proposta."
    )


def _sem_solucao(n: _Numeros, r: ResultadoCenario, cal: Calibracao) -> str:
    texto = "Não há alternativa por ajuste de taxas e bônus da proposta"
    if cal.custoProjetadoMinimo is not None:
        texto += (f": mesmo com os parâmetros no mínimo, o custo projetado seria "
                  f"{n.moeda('custoProjetadoMinimo', cal.custoProjetadoMinimo)}, acima do orçamento")
    texto += "."
    contratual = r.porBloco.get(CONTRATUAL)
    if contratual:
        texto += (f" As vendas sem regra aplicável seguem a taxa contratual e somam "
                  f"{n.moeda('custoContratualSemRegra', contratual)} no mês; essa parcela não é ajustável "
                  "pela proposta. Revise o público das regras ou o orçamento.")
    return texto


# ------------------------------------------------------------------------- limitações
def _limitacoes(n: _Numeros, r: ResultadoCenario, resumo: ResumoOrcamento | None,
                exclusoes: list[ItemExclusao], riscos: list[str]) -> list[str]:
    lim: list[str] = []
    if r.qtdFallbackContratual:
        lim.append(f"{n.inteiro('qtdFallbackContratual', r.qtdFallbackContratual)} venda(s) do público sem regra "
                   "aplicável foram calculadas pela taxa contratual (BASE_COMMISS).")
    if r.qtdMudancaFaixa:
        lim.append(f"{n.inteiro('qtdMudancaFaixa', r.qtdMudancaFaixa)} venda(s) mudam de faixa (e de regra) "
                   "em relação ao realizado por causa do multiplicador de vendas.")
    if r.qtdConflito:
        lim.append(f"{n.inteiro('qtdConflito', r.qtdConflito)} venda(s) têm regras empatadas e ficaram sem valor.")
    for e in exclusoes:
        if e.codigo == "CONFLITO_REGRAS" and r.qtdConflito:
            continue  # já citado acima pelo contador do cenário
        texto = f"{n.inteiro('exclusao.' + e.codigo, e.quantidade)} {_EXCLUSOES[e.codigo]}"
        if e.valorVendas is not None:
            texto += f" ({n.moeda('exclusao.' + e.codigo + '.valorVendas', e.valorVendas)} em vendas)"
        lim.append(texto + ".")
    if r.fatorProjecao is not None and resumo is not None:
        lim.append(f"A projeção supõe vendas uniformes no período: custo do mês × "
                   f"{n.inteiro('diasInclusivos', resumo.diasInclusivos)} dia(s) ÷ {n.inteiro('diasBase', 30)}.")
    if _e_100(r) and resumo is not None and not resumo.aptoEncaminhamentoGerente:
        lim.append(_bloqueio(n, resumo, exclusoes))
    for risco in riscos:
        lim.append(_risco(n, risco))
    lim.append("Resultado de simulação; não substitui a apuração oficial.")
    return lim


def _bloqueio(n: _Numeros, resumo: ResumoOrcamento, exclusoes: list[ItemExclusao]) -> str:
    """Remonta o motivo a partir dos dados: o texto pronto do resumo traz valores fora de `numeros`."""
    base = "Encaminhamento ao gerente bloqueado: "
    if resumo.orcamentoCampanha is None:
        return base + "orçamento monetário não informado."
    if resumo.statusCenario100 == "ACIMA_DO_TETO":
        return base + "o custo projetado do cenário de 100% excede o orçamento."
    impeditivas = sum(e.quantidade for e in exclusoes if e.impedeEncaminhamento)
    if impeditivas:
        return base + f"{n.inteiro('qtdNaoCalculaveis', impeditivas)} venda(s) não calculável(is)."
    return base + "consulte o resumo do orçamento."


def _risco(n: _Numeros, risco: str) -> str:
    """Os riscos vêm prontos de `cenarios.riscos`; os números deles também entram em `numeros`."""
    for i, m in enumerate(re.finditer(r"\d+", risco)):
        n.inteiro(f"risco.{i}", int(m.group()))
    return risco


# ----------------------------------------------------------------------------- utilidades
def _e_100(r: ResultadoCenario) -> bool:
    return r.multiplicadorVendas == Decimal("1")


def _lista(itens: list[str]) -> str:
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _dec_br(valor: Decimal) -> str:
    texto = format(valor.normalize(), "f")
    if "." in texto:
        inteiro, frac = texto.split(".")
    else:
        inteiro, frac = texto, ""
    inteiro = f"{int(inteiro):,}".replace(",", ".") if inteiro.lstrip("-").isdigit() else inteiro
    return f"{inteiro},{frac}" if frac else inteiro


def _brl(valor: Decimal) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
