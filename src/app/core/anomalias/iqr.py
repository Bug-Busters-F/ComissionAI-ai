"""
Estatística do IA-8 em Python puro e Decimal (reprodutível, sem pandas/numpy).

Quartis por interpolação linear inclusiva (mesmo método de QUARTIL.INC do Excel e do padrão do numpy):
posição = (n − 1) · p sobre os valores ordenados. Quartis arredondados a centavos (HALF_UP) e limites
calculados a partir deles, para que qualquer pessoa refaça a faixa a partir do que é devolvido.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def _cent(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def quantil(ordenados: list[Decimal], p: Decimal) -> Decimal:
    if not ordenados:
        raise ValueError("amostra vazia")
    pos = (len(ordenados) - 1) * p
    baixo = int(pos)  # pos ≥ 0
    frac = pos - baixo
    if baixo + 1 >= len(ordenados):
        return ordenados[-1]
    return ordenados[baixo] + (ordenados[baixo + 1] - ordenados[baixo]) * frac


@dataclass(frozen=True)
class Faixa:
    q1: Decimal
    mediana: Decimal
    q3: Decimal
    iqr: Decimal
    minimo: Decimal
    maximo: Decimal


def faixa_iqr(valores: list[Decimal], k: Decimal) -> Faixa:
    ordenados = sorted(valores)
    q1 = _cent(quantil(ordenados, Decimal("0.25")))
    med = _cent(quantil(ordenados, Decimal("0.5")))
    q3 = _cent(quantil(ordenados, Decimal("0.75")))
    iqr = q3 - q1
    return Faixa(q1, med, q3, iqr, _cent(q1 - k * iqr), _cent(q3 + k * iqr))
