"""
Agregação do IA-8: vendas -> total por colaborador/dia dentro de grupos comparáveis.

- Grupo = marca + código do cargo + descrição do cargo + competência. O cargo vem da venda (recorte do
  backend já o traz do RH) ou de `dadosRh`.
- Só existem observações para dias COM venda: dia sem venda não vira zero (evita alertas artificiais).
- Vendas sem RH/cargo, sem marca ou fora da competência são erros de carga explícitos, fora da análise.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.schemas.anomalia import ColaboradorRh, VendaAnomalia

LIMITE_IDS = 50

ChaveGrupo = tuple[int, int, str | None]  # (codMarca, codCargo, descriCargo normalizada)


def normalizar(texto: str | None) -> str | None:
    if texto is None:
        return None
    t = " ".join(texto.split()).upper()
    return t or None


def _mat(m: str | None) -> str | None:
    return m.strip().upper() if m and m.strip() else None


@dataclass
class Observacao:
    matricula: str
    data: date
    valor: Decimal = Decimal("0")
    venda_ids: list[str] = field(default_factory=list)


@dataclass
class Agregado:
    grupos: dict[ChaveGrupo, list[Observacao]]
    erros: dict[str, list[VendaAnomalia]]
    dias_com_venda: list[date]
    dias_na_competencia: int
    vendas_analisadas: int


def periodo(competencia: str) -> tuple[date, date]:
    ano, mes = map(int, competencia.split("-"))
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


def agregar(vendas: list[VendaAnomalia], rh: list[ColaboradorRh], competencia: str) -> Agregado:
    inicio, fim = periodo(competencia)
    por_mat = {_mat(c.matricula): c for c in rh}
    usar_rh = bool(rh)
    erros: dict[str, list[VendaAnomalia]] = defaultdict(list)
    obs: dict[ChaveGrupo, dict[tuple[str, date], Observacao]] = defaultdict(dict)
    dias: set[date] = set()
    analisadas = 0

    for v in vendas:
        if not inicio <= v.dataVenda <= fim:
            erros["FORA_DA_COMPETENCIA"].append(v)
            continue
        mat = _mat(v.matricula)
        colab = por_mat.get(mat) if mat else None
        cargo, descr = v.codCargo, v.descriCargo
        if colab is not None:
            if cargo is None:
                cargo, descr = colab.codCargo, colab.descriCargo
            elif descr is None and colab.codCargo == cargo:
                descr = colab.descriCargo
        if mat is None or cargo is None or (usar_rh and colab is None):
            erros["VENDA_SEM_RH"].append(v)
            continue
        if v.codMarca is None:
            erros["VENDA_SEM_MARCA"].append(v)
            continue
        dias.add(v.dataVenda)
        analisadas += 1
        o = obs[(v.codMarca, cargo, normalizar(descr))].setdefault((mat, v.dataVenda), Observacao(mat, v.dataVenda))
        o.valor += v.valorVenda
        o.venda_ids.append(v.id)

    grupos = {chave: sorted(d.values(), key=lambda o: (o.matricula, o.data)) for chave, d in obs.items()}
    return Agregado(grupos, dict(erros), sorted(dias), (fim - inicio).days + 1, analisadas)


def versao_dados(vendas: list[VendaAnomalia], rh: list[ColaboradorRh], competencia: str,
                 k: Decimal, amostra_minima: int) -> str:
    """sha256 canônico: mesma entrada (em qualquer ordem) e mesmos parâmetros -> mesmo hash."""
    def num(d: Decimal) -> str:
        return format(d.normalize(), "f")

    linhas_v = sorted(json.dumps([v.id, v.matricula, v.codLoja, v.codMarca, v.codCargo, v.descriCargo,
                                  num(v.valorVenda), v.dataVenda.isoformat()], ensure_ascii=False)
                      for v in vendas)
    linhas_rh = sorted(json.dumps([c.matricula, c.codLoja, c.codCargo, c.descriCargo], ensure_ascii=False)
                       for c in rh)
    corpo = json.dumps({"competencia": competencia, "k": num(k), "amostraMinima": amostra_minima,
                        "vendas": linhas_v, "rh": linhas_rh}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()
