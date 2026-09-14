"""
Normalizador determinístico de taxa e percentual de comissão (Task S1-A04).

Converte representações textuais ou numéricas de comissão (ex: '5%', '3,5%', '0.05', '5 por cento')
em Decimal de 4 casas decimais no intervalo (0.0000, 1.0000].
Gera pendências descritivas caso o valor seja inválido ou fora dos limites do MVP.
"""

import re
from decimal import Decimal, InvalidOperation


def normalizar_taxa(taxa_raw: str | int | float | Decimal | None) -> tuple[Decimal | None, list[str]]:
    """
    Normaliza a taxa de comissão para Decimal (0.0000 a 1.0000).

    Args:
        taxa_raw: Valor textual ou numérico extraído.

    Returns:
        Tupla (taxa_normalizada, pendencias).
    """
    pendencias: list[str] = []

    if taxa_raw is None:
        pendencias.append("Taxa/percentual de comissão não identificado no texto.")
        return None, pendencias

    raw_str = str(taxa_raw).strip().lower()
    if not raw_str:
        pendencias.append("Taxa/percentual de comissão vazio ou não informado.")
        return None, pendencias

    # Tratar expressões como "por cento", "porcento", "%"
    raw_str = raw_str.replace("por cento", "%").replace("porcento", "%")

    eh_percentual = "%" in raw_str
    # Limpar caracteres não numéricos exceto vírgula, ponto e sinal
    cleaned = raw_str.replace("%", "").strip()

    # Tratar vírgula decimal brasileira (ex: 3,5 -> 3.5)
    if "," in cleaned and "." in cleaned:
        # Caso tenha separador de milhar e decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    # Extrair o primeiro número compatível com regex
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        pendencias.append(f"Não foi possível converter a taxa '{taxa_raw}' em valor numérico.")
        return None, pendencias

    num_str = match.group(0)

    try:
        val = Decimal(num_str)
    except InvalidOperation:
        pendencias.append(f"Valor de taxa inválido: '{taxa_raw}'.")
        return None, pendencias

    if eh_percentual:
        taxa_decimal = (val / Decimal("100")).quantize(Decimal("0.0001"))
    else:
        # Se veio como número decimal (ex: 0.05) ou como inteiro maior que 1 sem %
        if val > Decimal("1.0"):
            # Ex: gestor digitou "5" querendo dizer 5%
            taxa_decimal = (val / Decimal("100")).quantize(Decimal("0.0001"))
        else:
            taxa_decimal = val.quantize(Decimal("0.0001"))

    # Validação do intervalo permitido no MVP (0 < taxa <= 1.0000)
    if taxa_decimal <= Decimal("0"):
        pendencias.append(
            f"Taxa de comissão deve ser maior que 0%. Valor informado resultou em {taxa_decimal * 100}%."
        )
        return None, pendencias

    if taxa_decimal > Decimal("1.0000"):
        pendencias.append(
            f"Taxa de comissão excessiva ({taxa_decimal * 100}%). O limite máximo permitido no MVP é 100.0000%."
        )
        return None, pendencias

    return taxa_decimal, pendencias
