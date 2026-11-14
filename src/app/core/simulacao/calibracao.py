"""
Calibração verificável por cenário excedido (IA-6 / BUG-119).

Para cada cenário cujo custo projetado passa do orçamento, procura UMA alternativa independente que
reduz proporcionalmente os parâmetros elegíveis das regras da proposta (taxa, bônus percentual e bônus
fixo) por um fator λ ∈ (0, 1]. Público, faixas e vigência não mudam: alterá-los mudaria o escopo.

Garantias:
- toda alternativa é REEXECUTADA no mesmo programa da simulação (template ou código aprovado); só é
  `ENQUADRADA` se o custo projetado recalculado couber no orçamento;
- o orçamento informado nunca é alterado;
- número de reexecuções e tempo limitados; ao estourar ou falhar, o status é `FALHA` e nenhuma
  alternativa é inventada;
- se nem os parâmetros no mínimo representável cabem (ex.: a parcela contratual sozinha passa do teto),
  o status é `SEM_SOLUCAO_VIAVEL`, com a restrição explicada.

O custo cai quando λ cai (faixas dependem do valor da venda, não da taxa), então a bisseção converge.
Nada aqui chama LLM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from app.schemas.proposta import AlteracaoParametro, BlocoProposta, Bonus, Calibracao, Cenario, ResultadoCenario

TAXA_ESCALA = Decimal("0.0001")
MOEDA_ESCALA = Decimal("0.01")
LAMBDA_ESCALA = Decimal("0.000001")


@dataclass
class Avaliacao:
    """Resultado de uma reexecução: o cenário consolidado ou o motivo da falha."""

    resultado: ResultadoCenario | None
    erro: str | None = None


Avaliador = Callable[[list[BlocoProposta], Cenario], Avaliacao]


def _arred(valor: Decimal, escala: Decimal) -> Decimal:
    return valor.quantize(escala, rounding=ROUND_HALF_UP)


def aplicar_fator(blocos: list[BlocoProposta], fator: Decimal | None) -> list[BlocoProposta]:
    """
    Escala taxa e bônus de cada regra. `fator=None` = parâmetros no mínimo representável (piso da busca).
    Nunca zera um parâmetro: as validações exigem taxa e bônus positivos.
    """
    saida: list[BlocoProposta] = []
    for b in blocos:
        def esc(v: Decimal | None, escala: Decimal) -> Decimal | None:
            if v is None:
                return None
            return escala if fator is None else max(escala, _arred(v * fator, escala))

        bonus = None
        if b.bonus is not None:
            bonus = Bonus(percentual=esc(b.bonus.percentual, TAXA_ESCALA),
                          valorFixo=esc(b.bonus.valorFixo, MOEDA_ESCALA))
        saida.append(b.model_copy(update={"taxa": esc(b.taxa, TAXA_ESCALA), "bonus": bonus}))
    return saida


def alteracoes(originais: list[BlocoProposta], ajustados: list[BlocoProposta]) -> list[AlteracaoParametro]:
    alt: list[AlteracaoParametro] = []
    for o, a in zip(originais, ajustados):
        pares = [("taxa", o.taxa, a.taxa)]
        if o.bonus is not None and a.bonus is not None:
            pares += [("bonus.percentual", o.bonus.percentual, a.bonus.percentual),
                      ("bonus.valorFixo", o.bonus.valorFixo, a.bonus.valorFixo)]
        for campo, antes, depois in pares:
            if antes is not None and antes != depois:
                alt.append(AlteracaoParametro(idLocal=o.idLocal, campo=campo, antes=antes, depois=depois))
    return alt


class Calibrador:
    """
    `max_tentativas` vale por cenário; `max_segundos` é um orçamento ÚNICO para todos os cenários da
    requisição (contado desde a criação), para caber no timeout de leitura do backend (60 s por padrão).
    """

    def __init__(self, avaliar: Avaliador, max_tentativas: int, max_segundos: float,
                 relogio: Callable[[], float] = time.monotonic) -> None:
        self._avaliar = avaliar
        self._max_tentativas = max_tentativas
        self._max_segundos = max_segundos
        self._relogio = relogio
        self._inicio = relogio()

    def calibrar(self, blocos: list[BlocoProposta], resultado: ResultadoCenario, cenario: Cenario,
                 orcamento: Decimal, assinatura: str) -> Calibracao:
        base = {"cenario": resultado.cenario, "multiplicadorVendas": cenario.multiplicadorVendas,
                "orcamento": orcamento, "custoProjetadoOriginal": resultado.custoProjetado,
                "assinaturaPrograma": assinatura}
        if resultado.custoProjetado is None:
            return Calibracao(**base, status="FALHA", tentativas=0,
                              motivo="O cenário não tem custo projetado para comparar com o orçamento.")
        if resultado.custoProjetado <= orcamento:
            return Calibracao(**base, status="NAO_NECESSARIA", tentativas=0)

        tentativas = 0

        def avaliar(fator: Decimal | None) -> tuple[Avaliacao, list[BlocoProposta]]:
            nonlocal tentativas
            tentativas += 1
            ajustados = aplicar_fator(blocos, fator)
            return self._avaliar(ajustados, cenario), ajustados

        # 1. Piso: se nem os parâmetros mínimos cabem, não há solução por ajuste de parâmetros.
        piso, _ = avaliar(None)
        if piso.resultado is None or piso.resultado.custoProjetado is None:
            return Calibracao(**base, status="FALHA", tentativas=tentativas,
                              motivo=f"A reexecução de verificação falhou: {piso.erro or 'sem custo projetado'}.")
        if piso.resultado.custoProjetado > orcamento:
            contratual = (piso.resultado.porBloco or {}).get("BASE_CONTRATUAL")
            motivo = (f"Mesmo com taxas e bônus da proposta no mínimo, o custo projetado seria "
                      f"R$ {_brl(piso.resultado.custoProjetado)}, acima do orçamento de R$ {_brl(orcamento)}.")
            if contratual:
                motivo += (f" As vendas sem regra aplicável (taxa contratual) somam R$ {_brl(contratual)} "
                           "antes da projeção e não são ajustáveis por esta proposta.")
            return Calibracao(**base, status="SEM_SOLUCAO_VIAVEL", tentativas=tentativas,
                              custoProjetadoMinimo=piso.resultado.custoProjetado, motivo=motivo)

        # 2. Bisseção em λ: guarda o maior λ cujo custo recalculado cabe.
        baixo, alto = Decimal("0"), Decimal("1")
        melhor: tuple[Decimal, ResultadoCenario, list[BlocoProposta]] | None = None
        while tentativas < self._max_tentativas:
            if self._relogio() - self._inicio > self._max_segundos:
                break
            meio = _arred((baixo + alto) / 2, LAMBDA_ESCALA)
            if meio in (baixo, alto):
                break
            av, ajustados = avaliar(meio)
            if av.resultado is None or av.resultado.custoProjetado is None:
                return Calibracao(**base, status="FALHA", tentativas=tentativas,
                                  motivo=f"A reexecução da alternativa falhou: {av.erro or 'sem custo projetado'}.")
            if av.resultado.custoProjetado <= orcamento:
                baixo = meio
                melhor = (meio, av.resultado, ajustados)
            else:
                alto = meio

        if melhor is None:
            return Calibracao(**base, status="FALHA", tentativas=tentativas,
                              motivo="Limite de reexecuções ou de tempo atingido antes de encontrar uma "
                                     "alternativa verificada; nenhuma sugestão foi gerada.")
        fator, res, ajustados = melhor
        assert res.custoProjetado is not None
        return Calibracao(
            **base,
            status="ENQUADRADA",
            tentativas=tentativas,
            fatorAjuste=fator,
            custoProjetadoRecalculado=res.custoProjetado,
            custoPropostoRecalculado=res.totalComissao,
            folga=orcamento - res.custoProjetado,
            alteracoes=alteracoes(blocos, ajustados),
        )


def _brl(valor: Decimal) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
