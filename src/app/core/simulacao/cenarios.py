"""
Cenários e comparação orçamentária da simulação (IA-5 / BUG-118).

Parte determinística que roda FORA do sandbox, com as mesmas definições do backend
(`SimulacaoCenariosService`, BACK-8), para que o enquadramento do Python e o do Java coincidam:

- população: vendas que pertencem ao público de ao menos uma regra (marca, loja, cargo, canal, matrícula),
  sem considerar faixa nem vigência; o mesmo escopo vale para todos os cenários;
- custo contratual: Σ HALF_UP(valor escalado × taxa contratual) sobre as vendas calculadas da população
  (vendas em conflito de regras ficam fora dos dois lados da comparação);
- custo proposto: comissão calculada pelo programa (regra da proposta ou fallback contratual);
- projeção: fator = dias inclusivos da campanha ÷ 30 (escala 6); custo projetado = HALF_UP(proposto × fator);
- enquadramento: custo projetado ≤ orçamento; o cenário de 100% define o encaminhamento ao gerente.

Nada aqui chama LLM. Uma venda que não pode ser calculada nunca vira zero: fica em `exclusoes`.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.schemas.proposta import (
    BlocoProposta,
    Cenario,
    EnquadramentoCenario,
    ItemExclusao,
    PendenciaAceita,
    PeriodoCampanha,
    ResultadoCenario,
    ResumoOrcamento,
    TaxaContratual,
)

CENT = Decimal("0.01")
DIAS_BASE_MES = Decimal("30")
CHAVE_CONTRATUAL = "BASE_CONTRATUAL"
MAX_IDS_EXCLUSAO = 50

CENARIOS_PADRAO = [
    Cenario(nome="Vendas 80%", multiplicadorVendas=Decimal("0.8")),
    Cenario(nome="Vendas 100%", multiplicadorVendas=Decimal("1")),
    Cenario(nome="Vendas 120%", multiplicadorVendas=Decimal("1.2")),
    Cenario(nome="Vendas 150%", multiplicadorVendas=Decimal("1.5")),
]

_MOTIVOS = {
    "FORA_DO_PUBLICO": "Venda fora do público de todas as regras da proposta; não entra no escopo da simulação.",
    "SEM_TAXA_CONTRATUAL": "Venda do público sem taxa no BASE_COMMISS para a marca e o cargo; não calculável.",
    "TAXA_CONTRATUAL_AMBIGUA": "Mais de uma taxa contratual possível para a marca e o cargo (descrição do cargo "
                               "ausente ou desconhecida); não calculável.",
    "CONFLITO_REGRAS": "Regras empatadas em especificidade para a mesma venda; não calculável até a proposta "
                       "desfazer o empate.",
}


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _norm(texto: str | None) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip().upper())


# --------------------------------------------------------------------------- população e taxa contratual
@dataclass
class Populacao:
    vendas: list[dict[str, Any]]
    exclusoes: list[ItemExclusao]
    modo_contratual: bool  # há taxas contratuais: custo contratual e fallback disponíveis


class ResolvedorTaxa:
    """Taxa por (marca, cargo, descrição); sem descrição, só resolve quando a taxa é única para o par."""

    def __init__(self, taxas: list[TaxaContratual]) -> None:
        self._exata: dict[tuple[int, int, str], Decimal] = {}
        self._par: dict[tuple[int, int], set[Decimal]] = {}
        for t in taxas:
            self._exata[(t.codMarca, t.codCargo, _norm(t.descriCargo))] = t.taxa
            self._par.setdefault((t.codMarca, t.codCargo), set()).add(t.taxa)

    def resolver(self, cod_marca: Any, cod_cargo: Any, descri_cargo: str | None) -> tuple[Decimal | None, str | None]:
        """Devolve (taxa, código de exclusão quando não resolvida)."""
        if cod_marca is None or cod_cargo is None:
            return None, "SEM_TAXA_CONTRATUAL"
        if descri_cargo:
            exata = self._exata.get((cod_marca, cod_cargo, _norm(descri_cargo)))
            if exata is not None:
                return exata, None
        candidatas = self._par.get((cod_marca, cod_cargo), set())
        if len(candidatas) == 1:
            return next(iter(candidatas)), None
        return None, ("TAXA_CONTRATUAL_AMBIGUA" if candidatas else "SEM_TAXA_CONTRATUAL")


def atende_publico(venda: dict[str, Any], bloco: BlocoProposta) -> bool:
    """Mesmas dimensões e comparações do template; faixa e vigência não definem público (igual ao backend)."""
    c = bloco.condicoes
    if c.matricula is not None and c.matricula != venda.get("matricula"):
        return False
    if c.codLoja is not None and c.codLoja != venda.get("codLoja"):
        return False
    if c.codCargo is not None and c.codCargo != venda.get("codCargo"):
        return False
    if c.canal is not None and c.canal.upper() != (venda.get("canal") or "PADRAO").upper():
        return False
    if c.codMarca is not None and c.codMarca != venda.get("codMarca"):
        return False
    return True


def preparar_populacao(
    vendas: list[dict[str, Any]], blocos: list[BlocoProposta], taxas: list[TaxaContratual]
) -> Populacao:
    """
    Separa o escopo da simulação. Cada venda do escopo recebe `taxaContratual` (str, como o sandbox espera).
    Sem nenhuma taxa contratual disponível (contrato anterior ao IA-5), o custo contratual não é calculado
    e vendas sem regra continuam fora da comissão, contadas como `vendasSemRegra`.
    """
    resolvedor = ResolvedorTaxa(taxas)
    modo_contratual = bool(taxas) or any(v.get("taxaContratual") is not None for v in vendas)
    escopo: list[dict[str, Any]] = []
    excluidas: dict[str, list[dict[str, Any]]] = {}
    for v in vendas:
        if not any(atende_publico(v, b) for b in blocos):
            excluidas.setdefault("FORA_DO_PUBLICO", []).append(v)
            continue
        if modo_contratual:
            taxa = v.get("taxaContratual")
            if taxa is None:
                taxa, motivo = resolvedor.resolver(v.get("codMarca"), v.get("codCargo"), v.get("descriCargo"))
                if taxa is None:
                    excluidas.setdefault(motivo or "SEM_TAXA_CONTRATUAL", []).append(v)
                    continue
            v = {**v, "taxaContratual": str(taxa)}
        escopo.append(v)
    exclusoes = [_item_exclusao(cod, lst) for cod, lst in excluidas.items()]
    return Populacao(escopo, exclusoes, modo_contratual)


def _item_exclusao(codigo: str, vendas: list[dict[str, Any]]) -> ItemExclusao:
    return ItemExclusao(
        codigo=codigo,  # type: ignore[arg-type]
        motivo=_MOTIVOS[codigo],
        quantidade=len(vendas),
        valorVendas=_q(sum((Decimal(str(v["valorVenda"])) for v in vendas), Decimal("0"))),
        vendaIds=[str(v.get("id", "")) for v in vendas[:MAX_IDS_EXCLUSAO]],
        impedeEncaminhamento=codigo != "FORA_DO_PUBLICO",
    )


# --------------------------------------------------------------------------- projeção
def periodo_projecao(periodo: PeriodoCampanha | None, competencia: str) -> tuple[date, date, int, Decimal]:
    """Dias inclusivos e fator de projeção; sem período, o mês inteiro da competência (fallback do backend)."""
    if periodo is not None:
        inicio, fim = periodo.dataInicio, periodo.dataFim
    else:
        ano, mes = (int(p) for p in competencia.split("-"))
        inicio, fim = date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])
    dias = (fim - inicio).days + 1
    return inicio, fim, dias, (Decimal(dias) / DIAS_BASE_MES).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- consolidação
@dataclass
class Consolidacao:
    resultados: list[ResultadoCenario]
    resumo: ResumoOrcamento
    exclusoes: list[ItemExclusao] = field(default_factory=list)
    erro: str | None = None  # reconciliação falhou: nenhum número pode ser devolvido


def consolidar(
    resultados: list[ResultadoCenario],
    brutos: list[dict[str, Any]],
    cenarios: list[Cenario],
    populacao: Populacao,
    orcamento: Decimal | None,
    periodo: PeriodoCampanha | None,
    competencia: str,
) -> Consolidacao:
    _, _, dias, fator = periodo_projecao(periodo, competencia)
    exclusoes = list(populacao.exclusoes)
    qtd = len(populacao.vendas)
    enriquecidos: list[ResultadoCenario] = []
    for res, bruto, cen in zip(resultados, brutos, cenarios):
        contadores = _contadores(bruto)
        if contadores is not None and sum(contadores.values()) - contadores["mudou"] != qtd:
            return Consolidacao([], _resumo_vazio(orcamento, dias, fator), exclusoes,
                                f"as vendas calculadas e não calculadas do cenário '{cen.nome}' não somam "
                                f"as {qtd} vendas do escopo.")
        contratual = None
        if populacao.modo_contratual:
            nao_calculado = _contratual_nao_calculado(bruto, contadores)
            if nao_calculado is not None:
                contratual = _q(_custo_contratual(populacao.vendas, cen.multiplicadorVendas) - nao_calculado)
        diferenca = _q(res.totalComissao - contratual) if contratual is not None else None
        projetado = _q(res.totalComissao * fator)
        delta_proj = _q(diferenca * fator) if diferenca is not None else None
        enriquecidos.append(res.model_copy(update={
            "multiplicadorVendas": cen.multiplicadorVendas,
            "custoContratual": contratual,
            "diferenca": diferenca,
            "diferencaPercentual": _percentual(diferenca, contratual),
            "fatorProjecao": fator,
            "custoProjetado": projetado,
            "deltaProjetado": delta_proj,
            "qtdVendas": qtd,
            "qtdRegraAplicada": contadores["regra"] if contadores else None,
            "qtdFallbackContratual": contadores["contratual"] if contadores else None,
            "qtdMudancaFaixa": contadores["mudou"] if contadores else None,
            "qtdConflito": contadores["conflito"] if contadores else None,
            "enquadramento": enquadrar(cen, qtd, orcamento, projetado, delta_proj),
        }))

    cen100 = next((r for r in enriquecidos if r.multiplicadorVendas == Decimal("1")), None)
    conflitos = cen100.qtdConflito if cen100 and cen100.qtdConflito else 0
    if conflitos:
        exclusoes.append(ItemExclusao(codigo="CONFLITO_REGRAS", motivo=_MOTIVOS["CONFLITO_REGRAS"],
                                      quantidade=conflitos, impedeEncaminhamento=True))
    return Consolidacao(enriquecidos, _resumo(cen100, orcamento, dias, fator, qtd, exclusoes), exclusoes)


def _contadores(bruto: dict[str, Any]) -> dict[str, int] | None:
    """Contadores do template; código livre pode não devolvê-los (aí a reconciliação por venda não se aplica)."""
    chaves = {"regra": "vendasComRegra", "contratual": "vendasFallbackContratual", "conflito": "vendasEmConflito",
              "sem": "vendasSemRegra", "mudou": "vendasMudancaFaixa"}
    if not all(isinstance(bruto.get(k), int) and not isinstance(bruto.get(k), bool) for k in chaves.values()):
        return None
    return {nome: bruto[k] for nome, k in chaves.items()}


def _contratual_nao_calculado(bruto: dict[str, Any], contadores: dict[str, int] | None) -> Decimal | None:
    """
    Custo contratual das vendas que o programa não calculou (conflito de regras), para o custo contratual
    comparar as mesmas vendas do custo proposto. None = há conflito e o valor não veio: a diferença contratual
    não é confiável e não é devolvida (em vez de um número errado).
    """
    if contadores is None or contadores["conflito"] == 0:
        return Decimal("0")
    valor = bruto.get("contratualEmConflito")
    if valor is None or isinstance(valor, bool):
        return None
    try:
        d = Decimal(str(valor))
    except ArithmeticError:
        return None
    return d if d.is_finite() and d >= 0 else None


def _custo_contratual(vendas: list[dict[str, Any]], mult: Decimal) -> Decimal:
    total = Decimal("0")
    for v in vendas:
        valor = _q(Decimal(str(v["valorVenda"])) * mult)
        total += _q(valor * Decimal(str(v["taxaContratual"])))
    return _q(total)


def _percentual(parte: Decimal | None, base: Decimal | None) -> Decimal | None:
    if parte is None or base is None:
        return None
    if base == 0:
        return Decimal("0.00")
    return (parte * 100 / base).quantize(CENT, rounding=ROUND_HALF_UP)


def enquadrar(cen: Cenario, qtd: int, orcamento: Decimal | None, projetado: Decimal,
              delta_proj: Decimal | None) -> EnquadramentoCenario:
    """Mesma regra de `calcularEnquadramentoCenario` do backend."""
    base = {"cenario": cen.nome, "multiplicadorVolume": cen.multiplicadorVendas, "totalVendasEscopo": qtd,
            "custoTotalProjetado": projetado, "deltaProjetado": delta_proj}
    if orcamento is None:
        return EnquadramentoCenario(**base, statusEnquadramento="NAO_APLICAVEL")
    dentro = projetado <= orcamento
    return EnquadramentoCenario(
        **base,
        orcamentoTeto=orcamento,
        statusEnquadramento="ENQUADRADO" if dentro else "ACIMA_DO_TETO",
        dentroDoOrcamento=dentro,
        saldoOrcamento=_q(orcamento - projetado),
        excedenteOrcamento=Decimal("0.00") if dentro else _q(projetado - orcamento),
        percentualUsoOrcamento=(projetado * 100 / orcamento).quantize(CENT, rounding=ROUND_HALF_UP),
    )


def _resumo(cen100: ResultadoCenario | None, orcamento: Decimal | None, dias: int, fator: Decimal, qtd: int,
            exclusoes: list[ItemExclusao]) -> ResumoOrcamento:
    status = cen100.enquadramento.statusEnquadramento if cen100 and cen100.enquadramento else "NAO_APLICAVEL"
    impeditivas = [e for e in exclusoes if e.impedeEncaminhamento]
    motivo: str | None = None
    if cen100 is None:
        motivo = "Não há cenário de 100% para definir o encaminhamento."
    elif orcamento is None:
        motivo = "Orçamento monetário não informado."
    elif status == "ACIMA_DO_TETO":
        assert cen100.enquadramento is not None
        motivo = (f"Custo projetado em 100% (R$ {_brl(cen100.custoProjetado)}) excede o teto orçamentário "
                  f"(R$ {_brl(orcamento)}) em R$ {_brl(cen100.enquadramento.excedenteOrcamento)}.")
    elif impeditivas:
        motivo = f"A simulação possui {sum(e.quantidade for e in impeditivas)} venda(s) não calculável(is)."
    return ResumoOrcamento(
        orcamentoCampanha=orcamento,
        diasInclusivos=dias,
        fatorProjecao=fator,
        totalVendasEscopoComum=qtd,
        escopoConsistenteQuatroCenarios=True,  # o mesmo `populacao.vendas` alimenta todos os cenários
        statusCenario100=status,
        valorEncaminhamento=cen100.custoProjetado if cen100 else None,
        aptoEncaminhamentoGerente=motivo is None,
        motivoBloqueioEncaminhamento=motivo,
    )


def _resumo_vazio(orcamento: Decimal | None, dias: int, fator: Decimal) -> ResumoOrcamento:
    return ResumoOrcamento(orcamentoCampanha=orcamento, diasInclusivos=dias, fatorProjecao=fator,
                           totalVendasEscopoComum=0, escopoConsistenteQuatroCenarios=False,
                           statusCenario100="NAO_APLICAVEL", aptoEncaminhamentoGerente=False,
                           motivoBloqueioEncaminhamento="Simulação sem números válidos.")


def _brl(valor: Decimal | None) -> str:
    if valor is None:
        return "-"
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def riscos(pendencias: list[PendenciaAceita]) -> list[str]:
    if not pendencias:
        return []
    por_base: dict[str, int] = {}
    for p in pendencias:
        por_base[p.tipoBase or "BASE"] = por_base.get(p.tipoBase or "BASE", 0) + 1
    partes = ", ".join(f"{n} em {b}" for b, n in sorted(por_base.items()))
    return [f"Resultado calculado com {len(pendencias)} pendência(s) de base aceita(s) com ressalva ({partes})."]
