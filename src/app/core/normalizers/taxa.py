"""
Normalizador determinístico de taxa e percentual de comissão (Task S1-A04).

Converte representações textuais ou numéricas de comissão (ex: '5%', '3,5%', '0.05', '5 por cento')
em Decimal de 4 casas decimais no intervalo (0.0000, 1.0000].
Gera pendências descritivas caso o valor seja inválido ou fora dos limites do MVP.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


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




# ---------------------------------------------------------------------------
# Ajustes sobre a comissão base (IA-5 / BUG-56)
# ---------------------------------------------------------------------------

_QUATRO_CASAS = Decimal("0.0001")

# "1 pp", "1 p.p.", "1 ponto percentual", "2 pontos"
_RE_PP = re.compile(r"\bp\.?\s?p\b\.?|\bpontos?\b")
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
# verbos/substantivos que indicam variação PROPORCIONAL da base ("aumentar 10%", "redução de 5%")
_RE_RELATIVO_AUMENTO = re.compile(r"\b(aument\w*|elev\w*|cresc\w*|relativ\w*|proporcional\w*)\b")
_RE_RELATIVO_REDUCAO = re.compile(r"\b(reduz\w*|reducao|diminu\w*|desconto)\b")
# termos que só dizem o sentido; com "%" sem "pp" não distinguem pontos de variação relativa
_RE_SOMA = re.compile(r"\b(mais|adicion\w*|acresc\w*|somar|soma|acima)\b|\+")
_RE_SUBTRACAO = re.compile(r"\b(menos|subtra\w*|abaixo|queda)\b|(?:^|\s)-\s*\d|\bbase\s*-")


@dataclass(frozen=True)
class OperacaoNormalizada:
    """Resultado da normalização de uma expressão de ajuste sobre a base."""

    tipo: str | None
    valor: Decimal | None
    pendencias: list[str] = field(default_factory=list)
    ambigua: bool = False


def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def interpretar_operacao(operacao_raw: str | int | float | Decimal | None) -> OperacaoNormalizada:
    """
    Classifica a expressão de ajuste sobre a comissão base (IA-5).

    - Pontos percentuais com sentido explícito ('mais 1 ponto percentual', '-0,5 pp')
      -> ADICIONAR_PP / REDUZIR_PP.
    - Variação proporcional explícita ('aumentar 1% sobre a base', 'redução de 5%')
      -> AUMENTAR_PERCENTUAL / REDUZIR_PERCENTUAL.
    - Valor sem sentido algum ('3%') -> TAXA_ABSOLUTA.
    - Expressões que não distinguem pontos de variação relativa ('mais 1%', 'base + 1%')
      ou sem sentido definido ('1 pp') -> ambígua, sem tipo, com pergunta ao gestor.

    O valor é sempre devolvido em escala decimal (1% ou 1 pp = 0.0100). Nada é presumido.

    Args:
        operacao_raw: Expressão textual ou numérica da operação.

    Returns:
        OperacaoNormalizada com tipo, valor, pendências e indicação de ambiguidade.
    """
    if operacao_raw is None or not str(operacao_raw).strip():
        return OperacaoNormalizada(None, None, ["Operação sobre a comissão base não informada."])

    original = str(operacao_raw).strip()
    texto = _sem_acentos(original.lower()).replace("por cento", "%").replace("porcento", "%")

    numeros = _RE_NUMERO.findall(texto)
    if not numeros:
        return OperacaoNormalizada(
            None, None, [f"Não foi possível identificar o valor numérico na operação '{original}'."]
        )
    if len({n.replace(",", ".") for n in numeros}) > 1:
        return OperacaoNormalizada(
            None, None, [f"A operação '{original}' cita mais de um valor; informe um único ajuste."], ambigua=True
        )
    try:
        valor = Decimal(numeros[0].replace(",", "."))
    except InvalidOperation:
        return OperacaoNormalizada(None, None, [f"Valor numérico inválido na operação: '{original}'."])
    if valor <= 0:
        return OperacaoNormalizada(None, None, [f"O valor do ajuste deve ser maior que zero: '{original}'."])
    delta = (valor / Decimal("100")).quantize(_QUATRO_CASAS)

    eh_pp = bool(_RE_PP.search(texto))
    rel_aumento = bool(_RE_RELATIVO_AUMENTO.search(texto))
    rel_reducao = bool(_RE_RELATIVO_REDUCAO.search(texto))
    soma = bool(_RE_SOMA.search(texto))
    subtracao = bool(_RE_SUBTRACAO.search(texto))
    aumento = rel_aumento or soma
    reducao = rel_reducao or subtracao

    if aumento and reducao:
        return OperacaoNormalizada(
            None, None,
            [f"A operação '{original}' indica aumento e redução ao mesmo tempo; informe o ajuste desejado."],
            ambigua=True,
        )

    if eh_pp:
        if not (aumento or reducao):
            return OperacaoNormalizada(
                None, None,
                [f"A operação '{original}' não diz se os pontos percentuais aumentam ou reduzem a base."],
                ambigua=True,
            )
        return OperacaoNormalizada("REDUZIR_PP" if reducao else "ADICIONAR_PP", delta)

    if rel_aumento or rel_reducao:
        return OperacaoNormalizada("REDUZIR_PERCENTUAL" if reducao else "AUMENTAR_PERCENTUAL", delta)

    if soma or subtracao:
        sinal = "-" if subtracao else "+"
        return OperacaoNormalizada(
            None, None,
            [
                f"A operação '{original}' é ambígua: pode ser {sinal}{valor} ponto(s) percentual(is) sobre a base "
                f"ou variação relativa de {sinal}{valor}% da base. Informe qual das duas."
            ],
            ambigua=True,
        )

    # sem sentido algum: valor absoluto ('3%' ou '0.03')
    taxa, pendencias = normalizar_taxa(original)
    if taxa is None:
        return OperacaoNormalizada(None, None, pendencias)
    return OperacaoNormalizada("TAXA_ABSOLUTA", taxa, pendencias)


def normalizar_operacao(
    operacao_raw: str | int | float | Decimal | None,
) -> tuple[str | None, Decimal | None, list[str]]:
    """
    Normaliza a operação sobre taxa/comissão (Task IA-5 / BUG-56).

    Atalho de `interpretar_operacao` que devolve apenas (tipo_operacao, valor_delta, pendencias).
    Expressões ambíguas voltam sem tipo e com a pendência explicando a dúvida.

    Args:
        operacao_raw: Expressão textual ou numérica da operação.

    Returns:
        Tupla (tipo_operacao, valor_delta, pendencias).
    """
    r = interpretar_operacao(operacao_raw)
    return r.tipo, r.valor, list(r.pendencias)


def calcular_taxa_com_operacao(
    taxa_base: Decimal,
    tipo: str,
    valor: Decimal,
    arredondar: bool = True,
) -> Decimal:
    """
    Calcula a taxa final a partir da taxa base e da operação (IA-5).

    Args:
        taxa_base: Taxa base (ex: Decimal('0.0250')).
        tipo: Tipo da operação ('ADICIONAR_PP', 'REDUZIR_PP', 'AUMENTAR_PERCENTUAL', 'REDUZIR_PERCENTUAL', 'TAXA_ABSOLUTA').
        valor: Valor delta ou taxa absoluta (ex: Decimal('0.0100')).
        arredondar: Se True, arredonda para 4 casas decimais usando ROUND_HALF_UP.

    Returns:
        Taxa final calculada.
    """
    if tipo == "ADICIONAR_PP":
        resultado = taxa_base + valor
    elif tipo == "REDUZIR_PP":
        resultado = taxa_base - valor
    elif tipo == "AUMENTAR_PERCENTUAL":
        resultado = taxa_base * (Decimal("1") + valor)
    elif tipo == "REDUZIR_PERCENTUAL":
        resultado = taxa_base * (Decimal("1") - valor)
    elif tipo == "TAXA_ABSOLUTA":
        resultado = valor
    else:
        raise ValueError(f"Tipo de operação desconhecido: '{tipo}'")

    if arredondar:
        return resultado.quantize(_QUATRO_CASAS, rounding=ROUND_HALF_UP)
    return resultado


def descrever_operacao(tipo: str, valor: Decimal) -> str:
    """
    Descreve a operação em português para explicações e mensagens (ex.: '+1,00 p.p.').

    Args:
        tipo: Tipo da operação.
        valor: Valor em escala decimal (0.0100 = 1 ponto ou 1%).

    Returns:
        Texto curto da operação.
    """
    pct = _pct(valor)
    return {
        "ADICIONAR_PP": f"+{pct} p.p. sobre a base",
        "REDUZIR_PP": f"-{pct} p.p. sobre a base",
        "AUMENTAR_PERCENTUAL": f"aumento relativo de {pct}% da base",
        "REDUZIR_PERCENTUAL": f"redução relativa de {pct}% da base",
        "TAXA_ABSOLUTA": f"taxa absoluta de {pct}%",
    }.get(tipo, tipo)


def formatar_percentual(taxa: Decimal) -> str:
    """Formata uma taxa decimal como percentual brasileiro ('0.02525' -> '2,525%')."""
    return f"{_pct(taxa)}%"


def _pct(valor: Decimal) -> str:
    texto = format((valor * 100).normalize(), "f")
    if "." not in texto:
        texto += ".00"
    inteiro, frac = texto.split(".")
    return f"{inteiro},{frac.ljust(2, '0')}"
