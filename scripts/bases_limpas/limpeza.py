"""
Regras de limpeza das bases de RH e Vendas (IA-9 / BUG-122).

Módulo puro: recebe as planilhas já lidas (cabeçalho + linhas) e devolve os registros limpos
e o registro de correções. Leitura e gravação de arquivos ficam em `gerar.py`.

Princípios:
- os arquivos originais nunca são alterados;
- nenhum valor de negócio é fabricado: o que não tem correção justificável vira pendência registrada;
- vendas legítimas são preservadas, mesmo quando fogem do padrão estatístico (material do IA-8).

Decisões do PO (14/11/2026):
- vendas duplicadas idênticas contam uma única vez (a chave é a mesma do `SalesRowValidator` do backend:
  matrícula, data, loja, marca e valor);
- vendas cuja matrícula não está no RH da competência são erro e ficam fora da base limpa.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

CENT = Decimal("0.01")

MESES = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}

# --------------------------------------------------------------------------- tipos de registro
# tipo: o que aconteceu; acao: o que foi feito com a linha
ERRO = "ERRO"
DUPLICIDADE = "DUPLICIDADE"
NORMALIZACAO = "NORMALIZACAO"
PENDENCIA = "PENDENCIA"

REMOVIDA = "REMOVIDA"
MANTIDA = "MANTIDA"
ALTERADA = "ALTERADA"


@dataclass(frozen=True)
class Coluna:
    chave: str
    cabecalho: str  # nome padronizado gravado na base limpa
    tipo: str  # data | inteiro | texto | decimal
    obrigatoria: bool = True
    aliases: tuple[str, ...] = ()

    def reconhece(self, cabecalho_original: Any) -> bool:
        n = normalizar_cabecalho(cabecalho_original)
        return n == normalizar_cabecalho(self.cabecalho) or n in self.aliases


# Ordem = ordem lida por posição pelo importador do backend (HrFileRowMapper / SalesFileRowMapper).
LAYOUT_RH: tuple[Coluna, ...] = (
    Coluna("data_ref", "Data_Ref", "data"),
    Coluna("cod_marca", "Cod_Marca", "inteiro"),
    Coluna("descr_marca", "Descri_Marca", "texto", aliases=("descrmarca",)),
    Coluna("cod_loja", "Cod_Loja", "inteiro"),
    Coluna("descr_loja", "Descr_Loja", "texto", aliases=("descrilojas", "descriloja")),
    Coluna("matricula", "Matricula", "texto"),
    Coluna("data_admiss", "Data_Admiss", "data"),
    Coluna("data_demiss", "Data_Demiss", "data", obrigatoria=False),
    Coluna("cod_cargo", "Cod_Cargo", "inteiro"),
    Coluna("descr_cargo", "Descri_Cargo", "texto", aliases=("descrcargo",)),
)

LAYOUT_VENDAS: tuple[Coluna, ...] = (
    Coluna("data_ref", "Date_Ref", "data", aliases=("dataref",)),
    Coluna("cod_marca", "Cod_Marca", "inteiro"),
    Coluna("descr_marca", "Descr_Marca", "texto", aliases=("descrimarca",)),
    Coluna("cod_loja", "Cod_Loja", "inteiro"),
    Coluna("descr_loja", "Descr_Loja", "texto", aliases=("descriloja",)),
    Coluna("matricula", "Matricula", "texto"),
    Coluna("valor", "Vlr_Venda", "decimal", aliases=("valorvenda", "vlrvendas")),
)

LAYOUT_TAXAS: tuple[Coluna, ...] = (
    Coluna("cod_marca", "Cod_Marca", "inteiro"),
    Coluna("descr_marca", "Descr_Marca", "texto", aliases=("descrimarca",)),
    Coluna("cod_cargo", "Cod_Cargo", "inteiro"),
    Coluna("descr_cargo", "Descri_Cargo", "texto", aliases=("descrcargo",)),
    Coluna("taxa", "%_Comiss", "decimal", aliases=("comiss", "taxa")),
)


@dataclass
class Correcao:
    arquivo: str
    linha: int | None
    matricula: str | None
    tipo: str
    acao: str
    regra: str
    campo: str | None
    antes: str | None
    depois: str | None
    justificativa: str

    CAMPOS = ("arquivo", "linha", "matricula", "tipo", "acao", "regra", "campo", "antes", "depois", "justificativa")

    def como_linha(self) -> list[Any]:
        return [getattr(self, c) for c in self.CAMPOS]


@dataclass
class Planilha:
    """Planilha já lida: `linhas` traz (número da linha no Excel, valores na ordem do cabeçalho)."""

    nome: str
    cabecalho: list[Any]
    linhas: list[tuple[int, tuple[Any, ...]]]


@dataclass
class Base:
    """Base convertida para o layout padrão. Cada registro guarda `_linha` (linha no arquivo original)."""

    nome: str
    tipo: str  # RH | VENDAS
    competencia: str  # YYYY-MM
    layout: tuple[Coluna, ...]
    registros: list[dict[str, Any]]
    lidas: int


@dataclass
class Registro:
    correcoes: list[Correcao] = field(default_factory=list)

    def add(self, arquivo: str, linha: int | None, matricula: str | None, tipo: str, acao: str, regra: str,
            justificativa: str, campo: str | None = None, antes: Any = None, depois: Any = None) -> None:
        self.correcoes.append(Correcao(
            arquivo, linha, matricula, tipo, acao, regra, campo,
            None if antes is None else _texto(antes), None if depois is None else _texto(depois), justificativa,
        ))


# --------------------------------------------------------------------------- utilidades
def normalizar_cabecalho(valor: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(valor or "").lower())


def competencia_do_nome(nome: str) -> str:
    """'BASE_VENDAS_JUL25.xlsx' -> '2025-07'."""
    m = re.search(r"(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[ _-]?(\d{2}|\d{4})", nome.upper())
    if not m:
        raise ValueError(f"Não foi possível identificar a competência no nome '{nome}'.")
    ano = int(m.group(2))
    ano = ano + 2000 if ano < 100 else ano
    return f"{ano:04d}-{MESES[m.group(1)]:02d}"


def _texto(v: Any) -> str:
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return str(v)


def _converter(valor: Any, tipo: str) -> Any:
    """Converte para o tipo do layout. Levanta ValueError quando o valor não é interpretável."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if tipo == "texto":
        return str(valor).strip()
    if tipo == "inteiro":
        if isinstance(valor, bool):
            raise ValueError("booleano")
        if isinstance(valor, int):
            return valor
        if isinstance(valor, float) and valor.is_integer():
            return int(valor)
        if isinstance(valor, str) and re.fullmatch(r"\s*-?\d+\s*", valor):
            return int(valor)
        raise ValueError(f"inteiro inválido: {valor!r}")
    if tipo == "decimal":
        try:
            d = Decimal(str(valor).strip().replace(",", ".")) if isinstance(valor, str) else Decimal(str(valor))
        except InvalidOperation as exc:
            raise ValueError(f"decimal inválido: {valor!r}") from exc
        if not d.is_finite():
            raise ValueError("decimal não finito")
        return d
    if tipo == "data":
        if isinstance(valor, datetime):
            return valor.date()
        if isinstance(valor, date):
            return valor
        if isinstance(valor, str):
            s = valor.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    pass
        raise ValueError(f"data inválida: {valor!r}")
    raise ValueError(f"tipo desconhecido: {tipo}")


# --------------------------------------------------------------------------- conversão
def converter_planilha(planilha: Planilha, tipo_base: str, layout: tuple[Coluna, ...], registro: Registro,
                       competencia: str | None = None) -> Base:
    """
    Mapeia colunas pelo nome (tolerando espaços e variações conhecidas), descarta colunas fora do layout,
    converte tipos e aplica as validações estruturais que o backend trata como impeditivas.
    Linhas com erro estrutural ficam fora da base limpa e são registradas.
    """
    nome = planilha.nome
    indices: dict[str, int] = {}
    for i, cab in enumerate(planilha.cabecalho):
        col = next((c for c in layout if c.reconhece(cab)), None)
        if col is None:
            if cab is not None and str(cab).strip():
                registro.add(nome, 1, None, NORMALIZACAO, REMOVIDA, "COLUNA_FORA_DO_LAYOUT",
                             "Coluna não pertence ao layout da base e foi removida da versão limpa.",
                             campo=str(cab), antes=cab)
            continue
        if col.chave in indices:
            raise ValueError(f"{nome}: coluna '{col.cabecalho}' aparece mais de uma vez.")
        indices[col.chave] = i
        if cab != col.cabecalho:
            registro.add(nome, 1, None, NORMALIZACAO, ALTERADA, "CABECALHO_PADRONIZADO",
                         "Cabeçalho padronizado (espaços e grafia); a ordem das colunas segue o importador.",
                         campo=col.cabecalho, antes=cab, depois=col.cabecalho)
    faltantes = [c.cabecalho for c in layout if c.chave not in indices]
    if faltantes:
        raise ValueError(f"{nome}: colunas obrigatórias ausentes: {', '.join(faltantes)}.")

    registros: list[dict[str, Any]] = []
    for num, valores in planilha.linhas:
        reg: dict[str, Any] = {"_linha": num}
        erros: list[str] = []
        for col in layout:
            bruto = valores[indices[col.chave]] if indices[col.chave] < len(valores) else None
            try:
                val = _converter(bruto, col.tipo)
            except ValueError as exc:
                erros.append(f"{col.cabecalho}: {exc}")
                val = None
            if col.tipo == "texto" and isinstance(bruto, str) and val is not None and val != bruto:
                registro.add(nome, num, None, NORMALIZACAO, ALTERADA, "TEXTO_APARADO",
                             "Espaços nas bordas removidos.", campo=col.cabecalho, antes=repr(bruto), depois=val)
            if col.tipo == "decimal" and val is not None:
                q = val.quantize(CENT, rounding=ROUND_HALF_UP)
                if q != val:
                    registro.add(nome, num, None, NORMALIZACAO, ALTERADA, "VALOR_ARREDONDADO",
                                 "Valor monetário ajustado para 2 casas (HALF_UP), mesma escala do backend.",
                                 campo=col.cabecalho, antes=val, depois=q)
                val = q
            if val is None and col.obrigatoria and not erros:
                erros.append(f"{col.cabecalho}: campo obrigatório ausente")
            reg[col.chave] = val
        erros += _validar_estrutura(reg, tipo_base, competencia)
        if erros:
            registro.add(nome, num, reg.get("matricula"), ERRO, REMOVIDA, "ERRO_ESTRUTURAL",
                         "Linha impeditiva para importação: " + "; ".join(erros))
            continue
        registros.append(reg)
    return Base(nome, tipo_base, competencia or "", layout, registros, len(planilha.linhas))


def _validar_estrutura(reg: dict[str, Any], tipo_base: str, competencia: str | None) -> list[str]:
    erros: list[str] = []
    if competencia and reg.get("data_ref") and reg["data_ref"].strftime("%Y-%m") != competencia:
        erros.append(f"data de referência {reg['data_ref']} fora da competência {competencia}")
    if tipo_base == "VENDAS":
        if reg.get("valor") is not None and reg["valor"] <= 0:
            erros.append("valor da venda deve ser maior que zero")
    if tipo_base == "RH":
        adm, dem = reg.get("data_admiss"), reg.get("data_demiss")
        if adm and dem and dem < adm:
            erros.append("data de demissão anterior à admissão")
    return erros


def carregar_taxas(planilha: Planilha, registro: Registro) -> dict[tuple[int, int, str], Decimal]:
    base = converter_planilha(planilha, "TAXAS", LAYOUT_TAXAS, registro)
    taxas: dict[tuple[int, int, str], Decimal] = {}
    for r in base.registros:
        taxas[(r["cod_marca"], r["cod_cargo"], _chave_cargo(r["descr_cargo"]))] = r["taxa"]
    return taxas


def _mesmos_dados(a: dict[str, Any], b: dict[str, Any], layout: tuple[Coluna, ...]) -> bool:
    return all(a[c.chave] == b[c.chave] for c in layout)


def _chave_cargo(descr: str | None) -> str:
    return re.sub(r"\s+", " ", (descr or "").strip().upper())


# --------------------------------------------------------------------------- limpeza por competência
def limpar_rh(rh: Base, taxas: dict[tuple[int, int, str], Decimal], registro: Registro) -> None:
    """Remove cópias idênticas; matrícula repetida com dados diferentes vira pendência (não há como escolher)."""
    por_mat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rh.registros:
        por_mat[r["matricula"]].append(r)
    manter: list[dict[str, Any]] = []
    for r in rh.registros:
        grupo = por_mat[r["matricula"]]
        if len(grupo) > 1:
            primeiro = grupo[0]
            if r is not primeiro and _mesmos_dados(r, primeiro, rh.layout):
                registro.add(rh.nome, r["_linha"], r["matricula"], DUPLICIDADE, REMOVIDA, "RH_DUPLICADO",
                             f"Cópia idêntica da linha {primeiro['_linha']}; mantida uma única ocorrência.")
                continue
            if r is not primeiro:
                registro.add(rh.nome, r["_linha"], r["matricula"], PENDENCIA, MANTIDA,
                             "RH_MATRICULA_REPETIDA_DIVERGENTE",
                             f"Matrícula repetida com dados diferentes da linha {primeiro['_linha']}; "
                             "exige decisão humana.")
        if (r["cod_marca"], r["cod_cargo"], _chave_cargo(r["descr_cargo"])) not in taxas:
            registro.add(rh.nome, r["_linha"], r["matricula"], PENDENCIA, MANTIDA, "SEM_TAXA_CONTRATUAL",
                         "Combinação marca/cargo/descrição sem taxa no BASE_COMMISS.",
                         campo="Cod_Cargo", antes=f"{r['cod_marca']}/{r['cod_cargo']}/{r['descr_cargo']}")
        manter.append(r)
    rh.registros = manter


def limpar_vendas(vendas: Base, rh: Base, taxas: dict[tuple[int, int, str], Decimal],
                  matriculas_por_competencia: dict[str, set[str]], registro: Registro) -> None:
    rh_por_mat = {r["matricula"]: r for r in rh.registros}
    vistas: dict[tuple[Any, ...], int] = {}
    manter: list[dict[str, Any]] = []
    for v in vendas.registros:
        mat = v["matricula"]
        rhm = rh_por_mat.get(mat)
        if rhm is None:
            outras = sorted(c for c, mats in matriculas_por_competencia.items()
                            if c != vendas.competencia and mat in mats)
            evidencia = (f"matrícula presente no RH de {', '.join(outras)}" if outras
                         else "matrícula ausente do RH de todas as competências")
            registro.add(vendas.nome, v["_linha"], mat, ERRO, REMOVIDA, "VENDA_SEM_RH",
                         f"Venda sem matrícula no RH de {vendas.competencia} ({evidencia}); "
                         "desconsiderada por decisão do PO.")
            continue
        chave = (mat, v["data_ref"], v["cod_loja"], v["cod_marca"], v["valor"])
        if chave in vistas:
            registro.add(vendas.nome, v["_linha"], mat, DUPLICIDADE, REMOVIDA, "VENDA_DUPLICADA",
                         f"Mesma matrícula, data, loja, marca e valor da linha {vistas[chave]}; "
                         "conta uma única vez por decisão do PO.")
            continue
        vistas[chave] = v["_linha"]
        _pendencias_venda(vendas, v, rhm, taxas, registro)
        manter.append(v)
    vendas.registros = manter


def _pendencias_venda(vendas: Base, v: dict[str, Any], rhm: dict[str, Any],
                      taxas: dict[tuple[int, int, str], Decimal], registro: Registro) -> None:
    nome, linha, mat = vendas.nome, v["_linha"], v["matricula"]
    if v["cod_loja"] != rhm["cod_loja"]:
        registro.add(nome, linha, mat, PENDENCIA, MANTIDA, "LOJA_DIVERGENTE_RH",
                     "Loja da venda difere da loja do colaborador no RH; mantida (pode ser atendimento em outra "
                     "loja) e relevante para regras filtradas por loja.",
                     campo="Cod_Loja", antes=f"RH={rhm['cod_loja']}", depois=f"venda={v['cod_loja']}")
    if v["cod_marca"] != rhm["cod_marca"]:
        registro.add(nome, linha, mat, PENDENCIA, MANTIDA, "MARCA_DIVERGENTE_RH",
                     "Marca da venda difere da marca do colaborador no RH; a taxa contratual depende da marca.",
                     campo="Cod_Marca", antes=f"RH={rhm['cod_marca']}", depois=f"venda={v['cod_marca']}")
    dem, adm, data = rhm.get("data_demiss"), rhm.get("data_admiss"), v["data_ref"]
    if dem and data > dem:
        registro.add(nome, linha, mat, PENDENCIA, MANTIDA, "VENDA_APOS_DEMISSAO",
                     "Data da venda posterior à demissão do colaborador.",
                     campo="Date_Ref", antes=f"demissão={dem.isoformat()}", depois=f"venda={data.isoformat()}")
    # Vendas datadas no dia 1º representam a competência; admissão no mesmo mês não é inconsistência.
    if adm and data < adm and (adm.year, adm.month) != (data.year, data.month):
        registro.add(nome, linha, mat, PENDENCIA, MANTIDA, "VENDA_ANTES_ADMISSAO",
                     "Venda em competência anterior à admissão do colaborador.",
                     campo="Date_Ref", antes=f"admissão={adm.isoformat()}", depois=f"venda={data.isoformat()}")
    if (v["cod_marca"], rhm["cod_cargo"], _chave_cargo(rhm["descr_cargo"])) not in taxas:
        registro.add(nome, linha, mat, PENDENCIA, MANTIDA, "SEM_TAXA_CONTRATUAL",
                     "Marca da venda + cargo do RH sem taxa no BASE_COMMISS.",
                     campo="Cod_Marca", antes=f"{v['cod_marca']}/{rhm['cod_cargo']}/{rhm['descr_cargo']}")


def verificar_cadastros(bases: Iterable[Base], registro: Registro) -> None:
    """Uma descrição por código de marca/loja e uma marca por loja, em todas as bases."""
    bases = list(bases)
    observados: dict[tuple[str, Any], Counter] = defaultdict(Counter)
    for b in bases:
        for r in b.registros:
            observados[("Descr_Marca", r["cod_marca"])][r["descr_marca"]] += 1
            observados[("Descr_Loja", r["cod_loja"])][r["descr_loja"]] += 1
            observados[("Cod_Marca da loja", r["cod_loja"])][r["cod_marca"]] += 1
    for (campo, codigo), contagem in sorted(observados.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        if len(contagem) > 1:
            registro.add("(todas as bases)", None, None, PENDENCIA, MANTIDA, "CADASTRO_INCONSISTENTE",
                         f"Código {codigo} aparece com valores diferentes em {campo}; nenhuma base foi alterada.",
                         campo=campo, antes=str(codigo),
                         depois="; ".join(f"{v} ({n})" for v, n in contagem.most_common()))


# --------------------------------------------------------------------------- saída
def linhas_saida(base: Base) -> list[list[Any]]:
    return [[r[c.chave] for c in base.layout] for r in base.registros]


def hash_conteudo(base: Base) -> str:
    """sha256 do conteúdo em forma canônica (independe de metadados do xlsx)."""
    h = hashlib.sha256()
    h.update("|".join(c.cabecalho for c in base.layout).encode())
    for linha in linhas_saida(base):
        h.update(b"\n" + "|".join("" if v is None else _texto(v) for v in linha).encode())
    return h.hexdigest()


def resumir(base: Base, registro: Registro) -> dict[str, Any]:
    do_arquivo = [c for c in registro.correcoes if c.arquivo == base.nome]
    removidas = Counter(c.regra for c in do_arquivo if c.acao == REMOVIDA and c.linha not in (None, 1))
    pendencias = Counter(c.regra for c in do_arquivo if c.tipo == PENDENCIA)
    normalizacoes = Counter(c.regra for c in do_arquivo if c.tipo == NORMALIZACAO)
    return {
        "arquivo": base.nome,
        "tipo": base.tipo,
        "competencia": base.competencia,
        "linhasLidas": base.lidas,
        "linhasMantidas": len(base.registros),
        "linhasRemovidas": dict(sorted(removidas.items())),
        "pendencias": dict(sorted(pendencias.items())),
        "normalizacoes": dict(sorted(normalizacoes.items())),
        "hashConteudo": hash_conteudo(base),
    }


def conferir_totais(base: Base, registro: Registro) -> None:
    """Invariante: lidas = mantidas + removidas (linhas de dados)."""
    removidas = sum(1 for c in registro.correcoes
                    if c.arquivo == base.nome and c.acao == REMOVIDA and c.linha not in (None, 1))
    if base.lidas != len(base.registros) + removidas:
        raise AssertionError(
            f"{base.nome}: {base.lidas} lidas != {len(base.registros)} mantidas + {removidas} removidas")
