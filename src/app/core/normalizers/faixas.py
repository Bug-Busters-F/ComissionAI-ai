"""
Normalizador determinístico de valores monetários e faixas de valor de venda (IA-2).

Entende: "R$ 1.500,00", "10 mil", "10k", "1,5 milhão", "10000".
Nunca estima: texto que não vira número gera pendência.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from app.schemas.proposta import FaixaValor

_MULTIPLICADORES = {
    "MIL": Decimal("1000"),
    "K": Decimal("1000"),
    "MILHAO": Decimal("1000000"),
    "MILHOES": Decimal("1000000"),
    "MI": Decimal("1000000"),
    "M": Decimal("1000000"),
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_valor_monetario(raw: str | None) -> tuple[Decimal | None, list[str]]:
    """Converte texto monetário em Decimal (escala 2). None + pendência se não for numérico."""
    if raw is None or not raw.strip():
        return None, []
    texto = _sem_acento(raw).upper().replace("R$", " ").strip()
    m = re.search(r"(\d[\d.,]*)\s*(MILHOES|MILHAO|MIL|MI|K|M)?\b", texto)
    if not m:
        return None, [f"Não foi possível interpretar o valor '{raw}'."]
    numero, sufixo = m.group(1), m.group(2)
    # Formato brasileiro: ponto = milhar, vírgula = decimal. Sem vírgula e com ponto
    # seguido de 3 dígitos, o ponto também é milhar.
    if "," in numero:
        numero = numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", numero):
        numero = numero.replace(".", "")
    try:
        valor = Decimal(numero)
    except InvalidOperation:
        return None, [f"Não foi possível interpretar o valor '{raw}'."]
    if sufixo:
        valor *= _MULTIPLICADORES[sufixo]
    if valor < 0:
        return None, [f"O valor '{raw}' não pode ser negativo."]
    return valor.quantize(Decimal("0.01")), []


def normalizar_faixa(
    min_raw: str | None,
    max_raw: str | None,
    min_inclusivo: bool | None = None,
    max_inclusivo: bool | None = None,
) -> tuple[FaixaValor | None, list[str]]:
    """
    Monta a FaixaValor. Sem indicação explícita de fronteira, usa o padrão
    [min, max) (mínimo incluído, máximo excluído), o que permite faixas contíguas.
    """
    if not (min_raw and min_raw.strip()) and not (max_raw and max_raw.strip()):
        return None, []
    pendencias: list[str] = []
    vmin, p1 = normalizar_valor_monetario(min_raw)
    vmax, p2 = normalizar_valor_monetario(max_raw)
    pendencias += p1 + p2
    if (min_raw and vmin is None) or (max_raw and vmax is None):
        return None, pendencias
    if vmin is not None and vmax is not None and vmax < vmin:
        return None, pendencias + [f"Faixa inconsistente: máximo ({vmax}) menor que o mínimo ({vmin})."]
    try:
        faixa = FaixaValor(
            min=vmin,
            max=vmax,
            minInclusivo=True if min_inclusivo is None else min_inclusivo,
            maxInclusivo=False if max_inclusivo is None else max_inclusivo,
        )
    except ValueError as exc:
        return None, pendencias + [str(exc)]
    return faixa, pendencias
