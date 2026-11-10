"""
Conversão determinística de números por extenso em português para Decimal (IA-1 / BUG-114).

Cobre o que aparece em pedidos reais de taxa/valor: unidades, dezenas, centenas, "mil" e
"milhão(ões)", compostos com "e" (ex: "mil e quinhentos", "vinte e cinco").

Nunca estima: qualquer palavra que não seja um numeral conhecido, um conector ("e") ou um
termo de contexto esperado (ex: "reais", "por cento") faz a conversão falhar (retorna None)
em vez de arriscar um palpite — mesmo princípio dos demais normalizadores desta pasta.
"""

import re
import unicodedata
from decimal import Decimal

_UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
_DEZENAS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
}
_CENTENAS = {
    "cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
    "quinhentos": 500, "seiscentos": 600, "setecentos": 700, "oitocentos": 800, "novecentos": 900,
}
_MULTIPLICADORES = {"mil": 1000, "milhao": 1_000_000, "milhoes": 1_000_000}

_NUMERAIS = set(_UNIDADES) | set(_DEZENAS) | set(_CENTENAS) | set(_MULTIPLICADORES)

# palavras de contexto que podem aparecer ao redor do número sem impedir a conversão
_IGNORADAS = {"reais", "real", "de"}

_CONECTOR = "e"


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def numero_por_extenso(raw: str | None) -> Decimal | None:
    """
    Converte um texto por extenso (ex: "dez", "mil e quinhentos", "cinco mil") em Decimal.

    Retorna None se houver qualquer palavra não reconhecida como numeral, conector ou termo
    de contexto esperado — não tenta adivinhar a partir de um reconhecimento parcial. Exige que
    o texto INTEIRO seja o número (ver `localizar_numero_por_extenso` para buscar dentro de frase).
    """
    if not raw or not raw.strip():
        return None
    if any(c.isdigit() for c in raw):
        return None  # não é extenso puro; o caminho numérico normal deve resolver
    texto = _sem_acento(raw).lower()
    tokens = [t for t in re.findall(r"[a-z]+", texto) if t not in _IGNORADAS]
    if not tokens or not all(t == _CONECTOR or t in _NUMERAIS for t in tokens):
        return None
    return _converter_tokens(tokens)


def localizar_numero_por_extenso(raw: str | None) -> Decimal | None:
    """
    Procura um número por extenso DENTRO de um texto maior (ex.: "mais dez por cento sobre a
    base"), ao contrário de `numero_por_extenso`, que exige que o texto inteiro seja só o número.
    Usado quando o número é só uma parte da frase (ex.: ajuste relativo sobre a base, IA-5).

    Pega a maior sequência contígua de numerais/conectores encontrada; não tenta somar números
    por extenso separados por outras palavras (ambiguidade não é resolvida, é descartada).
    """
    if not raw or not raw.strip():
        return None
    if any(c.isdigit() for c in raw):
        return None
    texto = _sem_acento(raw).lower()
    candidatos = [t for t in re.findall(r"[a-z]+", texto) if t not in _IGNORADAS]

    melhor: list[str] = []
    atual: list[str] = []
    for tok in candidatos:
        if tok in _NUMERAIS or tok == _CONECTOR:
            atual.append(tok)
        else:
            if len(atual) > len(melhor):
                melhor = atual
            atual = []
    if len(atual) > len(melhor):
        melhor = atual

    while melhor and melhor[0] == _CONECTOR:
        melhor = melhor[1:]
    while melhor and melhor[-1] == _CONECTOR:
        melhor = melhor[:-1]
    if not melhor:
        return None
    return _converter_tokens(melhor)


def _converter_tokens(tokens: list[str]) -> Decimal | None:
    total = 0
    grupo = 0
    teve_numeral = False
    for tok in tokens:
        if tok == _CONECTOR:
            continue
        teve_numeral = True
        if tok in _CENTENAS:
            grupo += _CENTENAS[tok]
        elif tok in _DEZENAS:
            grupo += _DEZENAS[tok]
        elif tok in _UNIDADES:
            grupo += _UNIDADES[tok]
        elif tok in _MULTIPLICADORES:
            grupo = grupo or 1
            total += grupo * _MULTIPLICADORES[tok]
            grupo = 0
    total += grupo
    if not teve_numeral:
        return None
    return Decimal(total)
