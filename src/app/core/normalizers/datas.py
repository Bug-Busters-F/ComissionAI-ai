"""
Normalizador determinístico de datas e vigência de regras (Task S1-A04).

Processa expressões em linguagem natural em Português (PT-BR), tais como nomes de meses,
intervalos ('de X a Y'), 'a partir de X', trimestres, semestres, e formatos de data explícitos
(ISO 8601 YYYY-MM-DD e brasileiro DD/MM/YYYY).

Utiliza ano_referencia ou data_referencia fornecidos no contexto.
"""

import calendar
import re
from datetime import date, datetime
from typing import Any

MESES_PT = {
    "janeiro": 1,
    "jan": 1,
    "fevereiro": 2,
    "fev": 2,
    "marco": 3,
    "março": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "maio": 5,
    "mai": 5,
    "junho": 6,
    "jun": 6,
    "julho": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "setembro": 9,
    "set": 9,
    "outubro": 10,
    "out": 10,
    "novembro": 11,
    "nov": 11,
    "dezembro": 12,
    "dez": 12,
}

TRIMESTRES = {
    "1": (1, 3),
    "1º": (1, 3),
    "1o": (1, 3),
    "primeiro": (1, 3),
    "q1": (1, 3),
    "2": (4, 6),
    "2º": (4, 6),
    "2o": (4, 6),
    "segundo": (4, 6),
    "q2": (4, 6),
    "3": (7, 9),
    "3º": (7, 9),
    "3o": (7, 9),
    "terceiro": (7, 9),
    "q3": (7, 9),
    "4": (10, 12),
    "4º": (10, 12),
    "4o": (10, 12),
    "quarto": (10, 12),
    "q4": (10, 12),
}

SEMESTRES = {
    "1": (1, 6),
    "1º": (1, 6),
    "1o": (1, 6),
    "primeiro": (1, 6),
    "s1": (1, 6),
    "2": (7, 12),
    "2º": (7, 12),
    "2o": (7, 12),
    "segundo": (7, 12),
    "s2": (7, 12),
}


def _extrair_ano_referencia(contexto: dict[str, Any] | None) -> int:
    """Extrai o ano de referência do contexto com fallback para a data de referência ou ano corrente."""
    if contexto:
        if "ano_referencia" in contexto and contexto["ano_referencia"]:
            try:
                return int(contexto["ano_referencia"])
            except (ValueError, TypeError):
                pass
        if "data_referencia" in contexto and contexto["data_referencia"]:
            dt_ref = contexto["data_referencia"]
            if isinstance(dt_ref, str):
                try:
                    return datetime.fromisoformat(dt_ref.strip()).year
                except ValueError:
                    pass
            elif isinstance(dt_ref, (date, datetime)):
                return dt_ref.year

    return date.today().year


def _ultimo_dia_mes(ano: int, mes: int) -> int:
    """Retorna o último dia de um determinado mês e ano."""
    return calendar.monthrange(ano, mes)[1]


def _parse_data_explicita(texto: str, ano_padrao: int) -> tuple[date | None, int | None]:
    """Tenta parsear uma data ISO (YYYY-MM-DD) ou formato brasileiro (DD/MM/YYYY ou DD/MM)."""
    texto = texto.strip()

    # Formato ISO YYYY-MM-DD
    match_iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", texto)
    if match_iso:
        y, m, d = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        try:
            return date(y, m, d), y
        except ValueError:
            return None, None

    # Formato BR DD/MM/YYYY
    match_br_ano = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", texto)
    if match_br_ano:
        d, m, y = int(match_br_ano.group(1)), int(match_br_ano.group(2)), int(match_br_ano.group(3))
        try:
            return date(y, m, d), y
        except ValueError:
            return None, None

    # Formato BR DD/MM (sem ano)
    match_br_sem_ano = re.search(r"\b(\d{1,2})[/.-](\d{1,2})\b", texto)
    if match_br_sem_ano:
        d, m = int(match_br_sem_ano.group(1)), int(match_br_sem_ano.group(2))
        try:
            return date(ano_padrao, m, d), ano_padrao
        except ValueError:
            return None, None

    return None, None


def _remover_acentos(texto: str) -> str:
    substituicoes = {
        "ã": "a", "á": "a", "à": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ü": "u",
        "ç": "c",
    }
    res = texto.lower()
    for k, v in substituicoes.items():
        res = res.replace(k, v)
    return res


def normalizar_datas(
    inicio_raw: str | None,
    fim_raw: str | None,
    contexto: dict[str, Any] | None = None,
) -> tuple[date | None, date | None, list[str]]:
    """
    Normaliza os dados brutos de vigência em dataInicio e dataFim (date ISO 8601).

    Args:
        inicio_raw: Expressão de início (ex: 'dezembro', '2026-10-01', 'a partir de novembro').
        fim_raw: Expressão de fim (ex: 'dezembro', '2026-12-31', None).
        contexto: Metadados contendo ano_referencia ou data_referencia.

    Returns:
        Tupla (dataInicio, dataFim, pendencias).
    """
    pendencias: list[str] = []
    ano_ref = _extrair_ano_referencia(contexto)

    if not inicio_raw and not fim_raw:
        pendencias.append("Data de início da vigência não identificada no texto.")
        return None, None, pendencias

    # Tratar caso onde início e fim vieram na mesma string em inicio_raw
    texto_combinado = f"{inicio_raw or ''} {fim_raw or ''}".strip()
    texto_norm = _remover_acentos(texto_combinado)

    # 1. Verificar se um ano explícito (ex: 2025, 2026, 2027) foi mencionado no texto
    match_ano = re.search(r"\b(20\d{2})\b", texto_norm)
    ano_usado = int(match_ano.group(1)) if match_ano else ano_ref

    data_inicio: date | None = None
    data_fim: date | None = None

    # 2. Verificar formato de trimestre (ex: 'primeiro trimestre', '1o trimestre', 'q1')
    match_trim = re.search(
        r"\b(1º|1o|primeiro|2º|2o|segundo|3º|3o|terceiro|4º|4o|quarto|q1|q2|q3|q4)\s*(?:trimestre|tri)?\b",
        texto_norm,
    )
    if match_trim and ("trimestre" in texto_norm or match_trim.group(1).startswith("q")):
        chave = match_trim.group(1)
        if chave in TRIMESTRES:
            m_ini, m_fim = TRIMESTRES[chave]
            data_inicio = date(ano_usado, m_ini, 1)
            data_fim = date(ano_usado, m_fim, _ultimo_dia_mes(ano_usado, m_fim))
            return data_inicio, data_fim, pendencias

    # 3. Verificar formato de semestre (ex: 'primeiro semestre', '1o semestre', 's1')
    match_sem = re.search(
        r"\b(1º|1o|primeiro|2º|2o|segundo|s1|s2)\s*(?:semestre|sem)?\b",
        texto_norm,
    )
    if match_sem and ("semestre" in texto_norm or match_sem.group(1).startswith("s")):
        chave = match_sem.group(1)
        if chave in SEMESTRES:
            m_ini, m_fim = SEMESTRES[chave]
            data_inicio = date(ano_usado, m_ini, 1)
            data_fim = date(ano_usado, m_fim, _ultimo_dia_mes(ano_usado, m_fim))
            return data_inicio, data_fim, pendencias

    # 4. Verificar intervalos de meses (ex: 'de janeiro a marco', 'entre outubro e dezembro', 'janeiro ate marco')
    match_intervalo_meses = re.search(
        r"\b(?:de|entre|desde)?\s*([a-z]+)\s*(?:a|ate|e|-)\s*([a-z]+)\b",
        texto_norm,
    )
    if match_intervalo_meses:
        m1_str, m2_str = match_intervalo_meses.group(1), match_intervalo_meses.group(2)
        if m1_str in MESES_PT and m2_str in MESES_PT:
            m1, m2 = MESES_PT[m1_str], MESES_PT[m2_str]
            data_inicio = date(ano_usado, m1, 1)
            data_fim = date(ano_usado, m2, _ultimo_dia_mes(ano_usado, m2))
            if data_fim < data_inicio:
                pendencias.append(
                    f"Mês de término ({m2_str}) não pode ser anterior ao mês de início ({m1_str})."
                )
                return None, None, pendencias
            return data_inicio, data_fim, pendencias

    # 5. Tratar datas explícitas para início e fim isoladamente
    if inicio_raw:
        dt_ini_exp, ano_ini = _parse_data_explicita(inicio_raw, ano_usado)
        if dt_ini_exp:
            data_inicio = dt_ini_exp
            if ano_ini:
                ano_usado = ano_ini

    if fim_raw:
        dt_fim_exp, _ = _parse_data_explicita(fim_raw, ano_usado)
        if dt_fim_exp:
            data_fim = dt_fim_exp

    # Se já encontrou ambas as datas explícitas
    if data_inicio and data_fim:
        if data_fim < data_inicio:
            pendencias.append(
                f"Data de término ({data_fim}) não pode ser anterior à data de início ({data_inicio})."
            )
            return None, None, pendencias
        return data_inicio, data_fim, pendencias

    # 6. Tratar mês único ou 'a partir de'
    ini_norm = _remover_acentos(inicio_raw or "")
    fim_norm = _remover_acentos(fim_raw or "")

    # Se foi especificado "a partir de [mês/data]"
    eh_a_partir = any(
        termo in ini_norm for termo in ["a partir de", "a contar de", "a comecar em", "a iniciar em"]
    )

    mes_ini = None
    for nome_mes, num_mes in MESES_PT.items():
        # Busca como palavra isolada
        if re.search(rf"\b{nome_mes}\b", ini_norm):
            mes_ini = num_mes
            break

    mes_fim = None
    for nome_mes, num_mes in MESES_PT.items():
        if re.search(rf"\b{nome_mes}\b", fim_norm):
            mes_fim = num_mes
            break

    if not data_inicio and mes_ini:
        data_inicio = date(ano_usado, mes_ini, 1)

    if not data_fim and mes_fim:
        data_fim = date(ano_usado, mes_fim, _ultimo_dia_mes(ano_usado, mes_fim))

    # Se foi informado apenas um único mês (ex: "em dezembro" -> inicio_raw="dezembro", fim_raw="dezembro" ou fim_raw=None mas não "a partir de")
    if data_inicio and not data_fim and not eh_a_partir and mes_ini and not fim_raw:
        # Quando se diz "em dezembro", vigora durante todo o mês de dezembro
        data_fim = date(ano_usado, mes_ini, _ultimo_dia_mes(ano_usado, mes_ini))

    # Se ainda não encontramos data de início
    if not data_inicio:
        pendencias.append(
            f"Não foi possível interpretar a data/período de início da vigência: '{inicio_raw}'."
        )

    # Validação de consistência se ambas as datas existem
    if data_inicio and data_fim:
        if data_fim < data_inicio:
            pendencias.append(
                f"A data final ({data_fim}) não pode ser anterior à data inicial ({data_inicio})."
            )
            return None, None, pendencias

    return data_inicio, data_fim, pendencias
